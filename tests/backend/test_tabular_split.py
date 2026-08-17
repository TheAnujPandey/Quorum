"""Tests for backend.ingestion.tabular_split."""

from backend.ingestion.tabular_split import (
    build_categorical_payload,
    build_row_narrative,
    classify_columns,
    row_source_ref,
)


class TestClassifyColumns:
    def test_narrative_by_hint(self):
        columns = ["Event Description", "Product", "Country"]
        sample = [
            {"Event Description": "Device failed during testing", "Product": "A", "Country": "US"},
            {"Event Description": "Normal operation observed", "Product": "B", "Country": "UK"},
        ]
        narrative, categorical, id_col = classify_columns(columns, sample)
        assert "Event Description" in narrative
        assert "Product" in categorical
        assert "Country" in categorical

    def test_id_column_detection(self):
        columns = ["complaint_id", "notes", "status"]
        sample = [
            {"complaint_id": "C001", "notes": "Long description of events that occurred", "status": "Open"},
        ]
        _, categorical, id_col = classify_columns(columns, sample)
        assert id_col == "complaint_id"
        assert "complaint_id" in categorical

    def test_narrative_by_length(self):
        columns = ["field_a", "field_b"]
        sample = [
            {"field_a": "x" * 100, "field_b": "Y"},
            {"field_a": "z" * 80, "field_b": "W"},
        ]
        narrative, categorical, _ = classify_columns(columns, sample)
        assert "field_a" in narrative
        assert "field_b" in categorical

    def test_empty_sample(self):
        columns = ["col_a", "col_b"]
        narrative, categorical, id_col = classify_columns(columns, [])
        assert len(narrative) == 0
        assert len(categorical) == 2


class TestBuildRowNarrative:
    def test_builds_narrative(self):
        row = {"Description": "The device failed", "Notes": "Replaced part"}
        result = build_row_narrative(row, ["Description", "Notes"])
        assert "Description: The device failed" in result
        assert "Notes: Replaced part" in result

    def test_skips_none_values(self):
        row = {"Description": None, "Notes": "Something"}
        result = build_row_narrative(row, ["Description", "Notes"])
        assert "Description" not in result
        assert "Notes: Something" in result

    def test_skips_empty_values(self):
        row = {"Description": "   ", "Notes": "Something"}
        result = build_row_narrative(row, ["Description", "Notes"])
        assert "Description" not in result


class TestBuildCategoricalPayload:
    def test_builds_payload(self):
        row = {"Product Name": "Widget A", "Country": "US"}
        result = build_categorical_payload(row, ["Product Name", "Country"])
        assert result["product_name"] == "Widget A"
        assert result["country"] == "US"

    def test_skips_none_and_empty(self):
        row = {"col_a": None, "col_b": "", "col_c": "value"}
        result = build_categorical_payload(row, ["col_a", "col_b", "col_c"])
        assert "col_a" not in result
        assert "col_b" not in result
        assert result["col_c"] == "value"

    def test_truncates_long_values(self):
        row = {"field": "x" * 1000}
        result = build_categorical_payload(row, ["field"])
        assert len(result["field"]) == 500


class TestRowSourceRef:
    def test_with_id_column(self):
        row = {"complaint_id": "VA2013-0455"}
        assert row_source_ref(row, "complaint_id", 1) == "row:VA2013-0455"

    def test_without_id_column(self):
        row = {"data": "something"}
        assert row_source_ref(row, None, 5) == "row:5"

    def test_empty_id_value_falls_back(self):
        row = {"complaint_id": "   "}
        assert row_source_ref(row, "complaint_id", 3) == "row:3"
