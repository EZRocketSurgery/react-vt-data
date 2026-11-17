# EIA Open Data API survey — 2026-11-17

This survey covers what the U.S. Energy Information Administration (EIA) Open Data
API v2 offers and which datasets include Vermont. It supports the proposal to add
energy data to the app (**[ISSUE LINK]**).

The figures come from a full crawl of the API's metadata on 2026-11-17: every route
and every data endpoint's columns, units, facets, frequencies and date range.
Vermont coverage was checked against each candidate dataset's facet values. No data
was loaded into the warehouse.

## Summary

- The API has **14 categories and 232 datasets**, from 1899 to projections through 2050.
- **Four datasets were checked and confirmed to include Vermont**, listed below.
  Each reports statewide figures, not town or county figures.
- 195 datasets offer annual data and 117 offer monthly data. The 16 weekly datasets
  cover petroleum and natural gas prices, supply and stocks. Hourly data exists only
  for the electricity grid.

## Vermont-relevant datasets

| Dataset | Endpoint | Vermont facet | Values | Frequency | Coverage |
| --- | --- | --- | --- | --- | --- |
| Retail electricity sales | `electricity/retail-sales` | `stateid=VT` (also `NEW`, New England) | price (cents/kWh), sales (million kWh), revenue (million $), customers; by sector | monthly, quarterly, annual | 2001-01 to 2026-08 |
| Heating oil and propane prices | `petroleum/pri/wfr` | `duoarea=SVT` | residential delivered price and wholesale price ($/gal) | weekly, monthly | 1990-10 to 2026-11 |
| State Energy Data System (SEDS) | `seds` | `stateId=VT` | production, consumption, prices and expenditures for every energy source and sector | annual | 1960 to 2024 |
| State electricity profile | `electricity/state-electricity-profiles/*` | `VT` (facet name varies by endpoint) | generation mix, supply and disposition, net metering customers and capacity, efficiency program costs and savings | annual | 1990 to 2025 (net metering and efficiency from 2013) |

On 2026-11-09, `petroleum/pri/wfr` reported Vermont residential heating oil at
$5.806/gal and propane at $3.994/gal.

**Checked, no Vermont rows:** densified biomass (wood pellets) is reported only by
multi-state region (East, South, West, U.S. total).

**Not checked:** other categories may also have Vermont rows. Natural gas prices and
consumption, for example, are reported by state. They were outside this survey's
scope.

## How the API is organized

Routes form a tree at most three levels deep. A route node lists its children, and
a data endpoint describes what it returns:

| Metadata field | Meaning | Example (`electricity/retail-sales`) |
| --- | --- | --- |
| `data` | value columns and units | `price` (cents per kilowatt-hour) |
| `facets` | dimensions to filter by | `stateid`, `sectorid` |
| `frequency` | available time steps | monthly, quarterly, annual |
| `startPeriod` / `endPeriod` | date coverage | 2001-01 to 2026-08 |

Data is requested from `<endpoint>/data/` with `data[]`, `facets[...]`, `frequency`
and date filters. For example, Vermont residential electricity prices:

```text
https://api.eia.gov/v2/electricity/retail-sales/data/?api_key=...&frequency=monthly&data[]=price&facets[stateid][]=VT&facets[sectorid][]=RES
```

Endpoints come in two shapes:

- **Named columns** (electricity, coal, nuclear outages, densified biomass): each
  measure has its own column and units.
- **Series style** (petroleum, natural gas, SEDS, STEO, AEO, IEO, total energy): one
  generic `value` column, with meaning and units set by facets such as `series`,
  `duoarea`, `product` and `process`. 195 of the 232 datasets use this shape.

## Categories

| Category | Datasets | Frequencies | Coverage |
| --- | --- | --- | --- |
| `petroleum` | 112 | weekly, monthly, annual, some daily | 1899–2026 |
| `natural-gas` | 53 | monthly, annual, some weekly and daily | 1925–2026 |
| `electricity` | 19 | hourly to annual | 1990–2026 |
| `coal` | 13 | quarterly, annual | 2000–2025 |
| `aeo` (Annual Energy Outlook) | 13 | annual | 2011–2050 |
| `densified-biomass` | 8 | monthly, annual | 2016–2026 |
| `ieo` (International Energy Outlook) | 4 | annual | 2010–2050 |
| `nuclear-outages` | 3 | daily | 2007–2026 |
| `co2-emissions` (deprecated, see SEDS) | 2 | annual | 1970–2022 |
| `seds` | 1 | annual | 1960–2024 |
| `total-energy` | 1 | monthly, annual | 1949–2026 |
| `steo` (Short-Term Energy Outlook) | 1 | monthly, quarterly, annual | 1974–2027 |
| `international` | 1 | monthly, quarterly, annual | 1949–2026 |
| `crude-oil-imports` | 1 | monthly, annual | 2009–2026 |

## Notes for a collector

- **Rate limits:** rapid requests return HTTP 429. A collector should pause between
  requests and retry with backoff.
- **Key:** requests need an API key, free from EIA. It would be read from
  `EIA_API_KEY`, as the Census collectors read `CENSUS_API_KEY`.
- **Unnamed datasets:** 182 of the 232 datasets have no `name` in their metadata.
  They are identified by path and facets.
- **Inconsistent metadata:** some descriptive columns (for example in
  `coal/mine-production`) return `[]` instead of a units object. `total-energy`
  reports an end period of 2121-12.
- **Inconsistent facet names:** the state facet is spelled `stateid`, `stateId`,
  `stateID` or `state` depending on the endpoint, even within
  `electricity/state-electricity-profiles`. A collector should take the facet name
  per endpoint, not assume one.
- **Deprecated route:** `co2-emissions` is deprecated and its data ends in 2022. EIA
  directs users to SEDS for state CO2 data.
