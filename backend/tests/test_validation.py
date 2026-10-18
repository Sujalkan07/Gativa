"""Unit tests for geometry validation and coordinate rules."""
import pytest
from pydantic import ValidationError
from app.models.schemas import GeoJSONPolygon


def test_valid_polygon():
    valid = {
        "type": "Polygon",
        "coordinates": [
            [
                [77.200, 28.600],
                [77.210, 28.600],
                [77.210, 28.610],
                [77.200, 28.610],
                [77.200, 28.600],
            ]
        ],
    }
    poly = GeoJSONPolygon(**valid)
    assert poly.type == "Polygon"
    assert len(poly.coordinates[0]) == 5


def test_invalid_polygon_too_few_points():
    invalid = {
        "type": "Polygon",
        "coordinates": [
            [
                [77.200, 28.600],
                [77.210, 28.600],
            ]
        ],
    }
    with pytest.raises(ValidationError):
        GeoJSONPolygon(**invalid)


def test_invalid_coordinates_out_of_range():
    out_of_range_lng = {
        "type": "Polygon",
        "coordinates": [
            [
                [195.0, 28.600],
                [195.1, 28.600],
                [195.1, 28.610],
                [195.0, 28.600],
            ]
        ],
    }
    with pytest.raises(ValidationError):
        GeoJSONPolygon(**out_of_range_lng)
