from datetime import datetime
from typing import Literal

from pydantic import BaseModel, model_validator

from query.clock import EASTERN_STD_TIME

MAX_YEAR = datetime.now(EASTERN_STD_TIME).year - 2


class RangeFilter(BaseModel):
    min: float | None = None
    max: float | None = None


class FilterRequest(BaseModel):
    # filters are keyed by human-readable label (e.g. "County", "Location", "Percent",
    # "year"). The schema shim (request_to_source) maps label -> backend column and
    # wraps them into a FilterSource. Values are either a discrete list or a RangeFilter
    # (location and the year range both travel inside filters).
    filters: dict[str, list[str] | RangeFilter] = {}
    include: list[str] | None = []


class FilterSpec(BaseModel):
    filter_table: str
    filters: dict[str, list[str] | RangeFilter] = {}


class DPSeriesRequest(BaseModel):
    name: str
    table: str
    category: str
    subcategory: str
    variable: str
    measure: str
    year_min: int = 2009
    year_max: int = MAX_YEAR


class CountyComparisonRequest(BaseModel):
    indicator: str


join_types = Literal["inner", "left", "spatial_intersect"]


class FilterSource(BaseModel):
    """
    Class *generated* from filterspecs, using the appropriate
    backend schema (which the API route dictates)
        filter_table: the table to source filters from
        filters: dictionary list of filters to apply (on that table)
        join_key: the column to join on -- NONE if spatial join
        join_type: what type of join to apply.

    Generally, it's on you to make sure that the table has the join key.

    NOTE: if join_type=spatial in any way, then:
        1) the SELECT clause in the main SQL must have a g.geom column exposed
        2) the join_key must be geom, which must be in the table.

    Args:
        BaseModel (_type_): _description_
    """

    filter_table: str
    filters: dict[str, list[str] | RangeFilter] = {}
    join_key: str = "OBJECT_ID"
    join_type: join_types = "inner"

    @model_validator(mode="after")
    def check_join_key(self) -> "FilterSource":
        if "spatial" in self.join_type and self.join_key != "geom":
            raise ValueError("join_key=geom required for spatial joins")
        return self
