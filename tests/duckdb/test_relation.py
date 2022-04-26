import re
from typing import Optional
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import polars as pl
import pytest

import patito as pt


@pytest.mark.skip(reason="Segmentation fault")
def test_relation():
    """Test functionality of Relation class."""
    # Create a new in-memory database with dummy data
    db = pt.Database()
    table_df = pl.DataFrame(
        {
            "column_1": [1, 2, 3],
            "column_2": ["a", "b", "c"],
        }
    )
    db.to_relation(table_df).create_table(name="table_name")
    table_relation = db.table("table_name")

    # A projection can be done in several different ways
    assert table_relation.project("column_1", "column_2") == table_relation.project(
        "column_1, column_2"
    )
    assert (
        table_relation.project("column_1, column_2")
        == table_relation[["column_1, column_2"]]
    )
    assert table_relation[["column_1, column_2"]] == table_relation
    assert table_relation.project("column_1") != table_relation.project("column_2")

    # We can also usekewyrod arguments to rename columns
    assert tuple(table_relation.project(column_3="column_1::varchar || column_2")) == (
        {"column_3": "1a"},
        {"column_3": "2b"},
        {"column_3": "3c"},
    )

    # The .get() method should only work if the filter matches a single row
    assert table_relation.get(column_1=1).column_2 == "a"

    # But raise if not exactly one matching row is found
    with pytest.raises(RuntimeError, match="Relation.get(.*) returned 0 rows!"):
        assert table_relation.get("column_1 = 4")
    with pytest.raises(RuntimeError, match="Relation.get(.*) returned 2 rows!"):
        assert table_relation.get("column_1 > 1")

    # The .get() should also accept a positional string
    assert table_relation.get("column_1 < 2").column_2 == "a"

    # And several positional strings
    assert table_relation.get("column_1 > 1", "column_1 < 3").column_2 == "b"

    # And a mix of positional and keyword arguments
    assert table_relation.get("column_1 < 2", column_2="a").column_2 == "a"

    # Order by statements shoud be respected when iterating over the relation
    assert tuple(table_relation.order("column_1 desc")) == (
        {"column_1": 3, "column_2": "c"},
        {"column_1": 2, "column_2": "b"},
        {"column_1": 1, "column_2": "a"},
    )

    # The plus operator acts as a union all
    assert (
        db.to_relation(table_df[:1])
        + db.to_relation(table_df[1:2])
        + db.to_relation(table_df[2:])
    ) == db.to_relation(table_df)

    # The union all must *not* remove duplicates
    assert db.to_relation(table_df) + db.to_relation(table_df) != db.to_relation(
        table_df
    )
    assert db.to_relation(table_df) + db.to_relation(table_df) == db.to_relation(
        pd.concat([table_df, table_df])
    )

    # You should be able to subscript columns
    assert table_relation["column_1"] == table_relation.project("column_1")
    assert table_relation[["column_1", "column_2"]] == table_relation

    # The relation's columns can be retrieved
    assert table_relation.columns == ["column_1", "column_2"]

    # You should be able to prefix and suffix all columns of a relation
    assert table_relation.add_prefix("prefix_").columns == [
        "prefix_column_1",
        "prefix_column_2",
    ]
    assert table_relation.add_suffix("_suffix").columns == [
        "column_1_suffix",
        "column_2_suffix",
    ]

    # You can drop one or more columns
    assert table_relation.drop("column_1").columns == ["column_2"]
    assert table_relation.project("*, 1 as column_3").drop(
        "column_1", "column_2"
    ).columns == ["column_3"]

    # You can rename columns
    assert set(table_relation.rename(column_1="new_name").columns) == {
        "new_name",
        "column_2",
    }

    # A value error must be raised if the source column does not exist
    with pytest.raises(
        ValueError,
        match=(
            "Column 'a' can not be renamed as it does not exist. "
            "The columns of the relation are: column_1, column_2."
        ),
    ):
        table_relation.rename(a="new_name")

    # Accessing non-existing attributes should raise AttributeError
    with pytest.raises(
        AttributeError,
        match="Relation has no attribute 'attribute_that_does_not_exist'",
    ):
        table_relation.attribute_that_does_not_exist

    # Both None, pd.NA, and nupmy.nan should be considered as null-values
    none_df = pd.DataFrame({"column_1": [1, None, pd.NA, np.nan]})
    none_relation = db.to_relation(none_df)
    assert none_relation.filter("column_1 is null") == none_df.iloc[1:]

    # The .inner_join() method should work as INNER JOIN, not LEFT or OUTER JOIN
    left_relation = db.to_relation(
        pd.DataFrame(
            {
                "left_primary_key": [1, 2],
                "left_foreign_key": [10, 20],
            }
        )
    )
    right_relation = db.to_relation(
        pd.DataFrame(
            {
                "right_primary_key": [10],
            }
        )
    )
    joined_table = pd.DataFrame(
        {
            "left_primary_key": [1],
            "left_foreign_key": [10],
            "right_primary_key": [10],
        }
    )
    assert (
        left_relation.inner_join(
            right_relation,
            on="left_foreign_key = right_primary_key",
        )
        == joined_table
    )

    # But the .left_join() method performs a LEFT JOIN
    left_joined_table = pd.DataFrame(
        {
            "left_primary_key": [1, 2],
            "left_foreign_key": [10, 20],
            "right_primary_key": [10, None],
        }
    )
    assert (
        left_relation.left_join(
            right_relation,
            on="left_foreign_key = right_primary_key",
        )
        == left_joined_table
    )


def test_rename_to_existing_column():
    """Renaming a column to overwrite another should work."""
    db = pt.Database()
    relation = db.to_relation("select 1 as a, 2 as b")
    renamed_relation = relation.rename(b="a")
    assert renamed_relation.columns == ["a"]
    assert renamed_relation.get().a == 2


def test_relation_aggregate_method():
    """Test for Relation.aggregate()."""
    db = pt.Database()
    relation = db.to_relation(
        pd.DataFrame(
            {
                "a": [1, 1, 2],
                "b": [10, 100, 1000],
                "c": [1, 2, 1],
            }
        )
    )
    aggregated_relation = relation.aggregate(
        "a",
        b_sum="sum(b)",
        group_by="a",
    )
    assert tuple(aggregated_relation) == (
        {"a": 1, "b_sum": 110},
        {"a": 2, "b_sum": 1000},
    )

    aggregated_relation_with_multiple_group_by = relation.aggregate(
        "a",
        "c",
        b_sum="sum(b)",
        group_by=["a", "c"],
    )
    assert tuple(aggregated_relation_with_multiple_group_by) == (
        {"a": 1, "c": 1, "b_sum": 10},
        {"a": 1, "c": 2, "b_sum": 100},
        {"a": 2, "c": 1, "b_sum": 1000},
    )


def test_relation_all_method():
    """Test for Relation.all()."""
    db = pt.Database()
    relation = db.to_relation(
        pd.DataFrame(
            {
                "a": [1, 2, 3],
                "b": [100, 100, 100],
            }
        )
    )

    assert not relation.all(a=100)
    assert relation.all(b=100)
    assert relation.all("a < 4", b=100)


@pytest.mark.skip(reason="Segmentation fault.")
def test_relation_case_method():
    db = pt.Database()

    df = pl.DataFrame(
        {"shelf_classification": ["A", "B", "A", "C"], "weight": [1, 2, 3, 4]}
    )

    correct_df = df.with_column(
        pl.Series([10, 20, 10, 0], dtype=pl.Int32).alias("max_weight")
    )
    correct_mapped_actions = db.to_relation(correct_df)

    mapped_actions = db.to_relation(df).case(
        from_column="shelf_classification",
        to_column="max_weight",
        mapping={"A": 10, "B": 20},
        default=0,
    )
    assert mapped_actions == correct_mapped_actions


def test_relation_coalesce_method():
    """Test for Relation.coalesce()."""
    db = pt.Database()
    df = pd.DataFrame(
        {"column_1": [1.0, None], "column_2": [None, "2"], "column_3": [3.0, None]}
    )
    relation = db.to_relation(df)
    coalesce_result = relation.coalesce(column_1=10, column_2="20").to_pandas()
    correct_coalesce_result = pd.DataFrame(
        {
            "column_1": [1.0, 10.0],
            "column_2": ["20", "2"],
            "column_3": [3.0, None],
        }
    )
    pd.testing.assert_frame_equal(coalesce_result, correct_coalesce_result)


def test_relation_union_method():
    """Test for Relation.union and Relation.__add__."""
    db = pt.Database()
    left = db.to_relation("select 1 as a, 2 as b")
    right = db.to_relation("select 200 as b, 100 as a")
    correct_union = pd.DataFrame(
        {
            "a": [1, 100],
            "b": [2, 200],
        }
    )
    assert left + right == correct_union
    assert right + left == correct_union[["b", "a"]][::-1]

    assert left.union(right) == correct_union
    assert right.union(left) == correct_union[["b", "a"]][::-1]

    incompatible = db.to_relation("select 1 as a")
    with pytest.raises(
        TypeError,
        match="Union between relations with different column names is not allowed.",
    ):
        incompatible + right
    with pytest.raises(
        TypeError,
        match="Union between relations with different column names is not allowed.",
    ):
        left + incompatible


def test_relation_model_functionality():
    """The end-user should be able to specify the constructor for row values."""
    db = pt.Database()

    # We have two rows in our relation
    first_row_relation = db.to_relation("select 1 as a, 2 as b")
    second_row_relation = db.to_relation("select 3 as a, 4 as b")
    relation = first_row_relation + second_row_relation

    # Iterating over the relation should yield the same as .get()
    iterator_value = tuple(relation)[0]
    get_value = relation.get("a = 1")
    assert iterator_value == get_value
    assert iterator_value.a == 1
    assert get_value.a == 1
    assert iterator_value.b == 2
    assert get_value.b == 2

    # The end-user should be able to specify a custom row constructor
    model_mock = MagicMock(return_value="mock_return")
    new_relation = relation.set_model(model_mock)
    assert new_relation.get("a = 1") == "mock_return"
    model_mock.assert_called_with(a=1, b=2)

    # We create a custom model
    class MyModel(pt.Model):
        a: int
        b: str

    # Some dummy data
    dummy_df = MyModel.example({"a": [1, 2], "b": ["one", "two"]})
    dummy_relation = db.to_relation(dummy_df)

    # Initially the relation has no custom model and it is dynamically constructed
    assert dummy_relation.model is None
    assert not isinstance(
        dummy_relation.limit(1).get(),
        MyModel,
    )

    # MyRow can be specified as the deserialization class with Relation.set_model()
    assert isinstance(
        dummy_relation.set_model(MyModel).limit(1).get(),
        MyModel,
    )

    # A custom relation class which specifies this as the default model
    class MyRelation(pt.Relation):
        model = MyModel

    assert isinstance(
        MyRelation(dummy_relation._relation, database=db).limit(1).get(),
        MyModel,
    )

    # But the model is "lost" when we use schema-changing methods
    assert not isinstance(
        dummy_relation.set_model(MyModel).limit(1).project("a").get(),
        MyModel,
    )


def test_row_sql_type_functionality():
    """Tests for mapping pydantic types to DuckDB SQL types."""
    # Two nullable and two non-nullable columns
    class OptionalRow(pt.Model):
        a: str
        b: float
        c: Optional[str]
        d: Optional[bool]

    assert OptionalRow.non_nullable_columns == {"a", "b"}
    assert OptionalRow.nullable_columns == {"c", "d"}

    # All different types of SQL types
    class TypeModel(pt.Model):
        a: str
        b: int
        c: float
        d: Optional[bool]

    assert TypeModel.sql_types == {
        "a": "VARCHAR",
        "b": "BIGINT",
        "c": "DOUBLE",
        "d": "BOOLEAN",
    }


def test_fill_missing_columns():
    """Tests for Relation.with_missing_{nullable,defaultable}_columns."""

    class MyRow(pt.Model):
        # This can't be filled
        a: str
        # This can be filled with default value
        b: Optional[str] = "default_value"
        # This can be filled with null
        c: Optional[str]
        # This can be filled with null, but will be set
        d: Optional[float]
        # This can befilled with null, but with a different type
        e: Optional[bool]

    # We check if defaults are easily retrievable from the model
    assert MyRow.defaults == {"b": "default_value"}

    db = pt.Database()
    df = pd.DataFrame({"a": ["mandatory"], "d": [10.5]})
    relation = db.to_relation(df).set_model(MyRow)

    # Missing nullable columns b, c, and e are filled in with nulls
    filled_nullables = relation.with_missing_nullable_columns()
    assert filled_nullables.set_model(None).get() == {
        "a": "mandatory",
        "b": None,
        "c": None,
        "d": 10.5,
        "e": None,
    }
    # And these nulls are properly typed
    assert filled_nullables.sql_types == {
        "a": "VARCHAR",
        "b": "VARCHAR",
        "c": "VARCHAR",
        "d": "DOUBLE",
        "e": "BOOLEAN",
    }

    # Now we fill in the b column with "default_value"
    filled_defaults = relation.with_missing_defaultable_columns()
    assert filled_defaults.set_model(None).get().dict() == {
        "a": "mandatory",
        "b": "default_value",
        "d": 10.5,
    }
    assert filled_defaults.sql_types == {
        "a": "VARCHAR",
        "b": "VARCHAR",
        "d": "DOUBLE",
    }


def test_relation_insert_into():
    """Relation.insert_into() should automatically order columnns correctly."""
    db = pt.Database()
    db.execute(
        """
        create table foo (
            a integer,
            b integer
        )
    """
    )
    db.to_relation("select 2 as b, 1 as a").insert_into(table_name="foo")
    row = db.table("foo").get()
    assert row.a == 1
    assert row.b == 2

    with pytest.raises(
        TypeError,
        match=re.escape(
            "Relation is missing column(s) {'a'} "
            "in order to be inserted into table 'foo'!"
        ),
    ):
        db.to_relation("select 2 as b, 1 as c").insert_into(table_name="foo")


def test_polars_support():
    # Test converting a polars DataFrame to patito relation
    df = pl.DataFrame(data={"column_1": ["a", "b", None], "column_2": [1, 2, None]})
    correct_dtypes = [pl.Utf8, pl.Int64]
    assert df.dtypes == correct_dtypes
    db = pt.Database()
    relation = db.to_relation(df)
    assert relation.get(column_1="a").column_2 == 1

    # Test converting back again the other way
    roundtrip_df = relation.to_df()
    assert roundtrip_df.frame_equal(df)
    assert roundtrip_df.dtypes == correct_dtypes

    # Assert that .to_df() always returns a DataFrame.
    assert isinstance(relation["column_1"].to_df(), pl.DataFrame)

    # Assert that .to_df() returns an empty DataFrame when the table has no rows
    empty_dataframe = relation.filter(column_1="missing-column").to_df()
    # assert empty_dataframe == pl.DataFrame(columns=["column_1", "column_2"])
    # assert empty_dataframe.frame_equal(pl.DataFrame(columns=["column_1", "column_2"]))

    # The datatype should be preserved
    assert empty_dataframe.dtypes == correct_dtypes

    # A model should be able to be instantiated with a polars row
    class MyModel(pt.Model):
        a: int
        b: str

    my_model_df = pl.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    with pytest.raises(
        ValueError,
        match=r"MyModel.from_polars\(\) can only be invoked with exactly 1 row.*",
    ):
        MyModel.from_polars(my_model_df)

    my_model = MyModel.from_polars(my_model_df.head(1))
    assert my_model.a == 1
    assert my_model.b == "x"


def test_series_vs_dataframe_behavior():
    """Test Relation.to_series()."""
    db = pt.Database()
    relation = db.to_relation("select 1 as column_1, 2 as column_2")

    # Selecting multiple columns should yield a DataFrame
    assert isinstance(relation[["column_1", "column_2"]].to_df(), pl.DataFrame)

    # Selecting a single column, but as an item in a list, should yield a DataFrame
    assert isinstance(relation[["column_1"]].to_df(), pl.DataFrame)

    # Selecting a single column as a string should also yield a DataFrame
    assert isinstance(relation["column_1"].to_df(), pl.DataFrame)

    # But .to_series() should yield a series
    series = relation["column_1"].to_series()
    assert isinstance(series, pl.Series)

    # The name should also be set correctly
    assert series.name == "column_1"

    # And the content should be correct
    correct_series = pl.Series([1], dtype=pl.Int32).alias("column_1")
    assert series.series_equal(correct_series)

    # To series will raise a type error if invoked with anything other than 1 column
    with pytest.raises(TypeError, match=r".*2 columns, while exactly 1 is required.*"):
        relation.to_series()