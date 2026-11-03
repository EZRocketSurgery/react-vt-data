"""
Census Utility Functions
"""

import json
from pathlib import Path

import pandas as pd
import requests

CENSUS_CACHE_DIR = Path(__file__).resolve().parent.parent / "Data/census"


def split_name_col(census_gdf, keep_name: bool = True):
    """
    Splits the "NAME" column into "Jurisdiction" and "County" columns.
    By default the original NAME column is preserved (keep_name=True).

    @param census_gdf: A census-style DataFrame with a "NAME" column.
    @param keep_name:  When True (default) the NAME column is kept alongside
                       the new Jurisdiction and County columns.
    @return: The dataset with Jurisdiction and County added.
    """
    census_gdf[["Jurisdiction", "County"]] = census_gdf["NAME"].str.extract(
        r"^(.*?),\s*(.*?) County,"
    )
    if not keep_name:
        census_gdf = census_gdf.drop(columns="NAME")

    if "year" in census_gdf.columns:
        census_gdf["year"] = census_gdf["year"].astype(str)
    return census_gdf


def get_census_cols(year: int) -> pd.DataFrame:
    # Path for cached census variable dataset
    cache_path = CENSUS_CACHE_DIR / f"acs5_profile_variables_{year}.json"
    if cache_path.exists():
        with cache_path.open() as f:
            data = json.load(f)
    else:
        url = f"https://api.census.gov/data/{year}/acs/acs5/profile/variables.json"

        response = requests.get(url)
        response.raise_for_status()

        data = response.json()["variables"]

        CENSUS_CACHE_DIR.mkdir(parents=True, exist_ok=True)

        with cache_path.open("w") as f:
            json.dump(data, f, indent=2)

    items_to_remove = ["for", "in", "ucgid"]
    for item in items_to_remove:
        data.pop(item, None)

    df = pd.DataFrame.from_dict(data, orient="index")
    df.index.name = "Name"
    df = df.reset_index()[["Name", "label"]].rename(columns={"label": "Label"})

    return df


def split_to_cols(s, cols):
    parts = [p.strip() for p in s.split("!!")]

    while len(parts) < len(cols):
        parts.append("")

    first = parts[0 : len(cols) - 1]
    second = parts[len(cols) - 1 :]
    second = [": ".join(second)]

    return first + second


def relabel_census_cols(df):
    # Splits apart the labels so we can filter across them
    cols = ["Measure", "Category", "Subcategory", "Variable"]
    # Keep only rows where the label is structured by "!!" (Issues with "Geography" rows)
    df_clean = df[df["Label"].str.contains("!!")].copy()
    # Reset index to avoid merging issues
    df_clean.reset_index(drop=True, inplace=True)
    # Preserve the original census variable code (e.g. "DP05_0001E") and name it "Variable_Code"
    df_clean = df_clean.rename(columns={"Name": "Variable_Code"})

    splits = df_clean["Label"].apply(lambda x: list(split_to_cols(x, cols)))
    splits_df = pd.DataFrame(splits.tolist(), columns=cols)

    # Create the total categories
    splits_df.loc[
        (splits_df["Subcategory"].notna()) & (splits_df["Variable"] == ""), "Variable"
    ] = "Total"

    name_df = pd.concat([df_clean, splits_df], axis=1)

    return name_df


def merge_census_cols(name_df, data_gdf, id_vars: list | None):
    id_vars = id_vars or ["GEOID", "geometry", "Jurisdiction", "County"]

    # Melt the gdf into tidy format
    data_gdf[id_vars]
    df_long = data_gdf.melt(
        id_vars=id_vars,
        value_vars=data_gdf.columns.difference(id_vars),
        var_name="Code",
        value_name="Value",
    )

    # The variable list names only estimates (E, PE), so the margins of error
    # (M, PM) would drop out below. Attach each one to its estimate's row as
    # MOE instead: DP03_0062M -> DP03_0062E, DP03_0062PM -> DP03_0062PE.
    is_moe = df_long["Code"].str.fullmatch(r"\w+_\d+P?M")
    moe = (
        df_long[is_moe]
        .assign(Code=lambda d: d["Code"].str[:-1] + "E")
        .rename(columns={"Value": "MOE"})
    )
    df_long = df_long[~is_moe].merge(moe, on=[*id_vars, "Code"], how="left")

    # Merge to get the right names and drop the cols (keep Variable_Code - the
    # original census variable code - for downstream lineage)
    return (
        pd.merge(left=df_long, right=name_df, left_on="Code", right_on="Variable_Code")
        .rename(columns={"Label": "Source_Label"})
        .drop(columns=["Code"])
    )


def tidy_census(census_gdf, year=2019, id_vars: list | None = None):
    # wrapper func to rename codes in func
    name_df = get_census_cols(year)
    name_df = relabel_census_cols(name_df)
    return merge_census_cols(name_df, census_gdf, id_vars)


if __name__ == "__main__":
    # Example run to debug
    get_census_cols(2024)
