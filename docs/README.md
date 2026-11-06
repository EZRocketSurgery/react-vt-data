# Documentation

New here? Start with the [Codebase Primer](Codebase_Primer.md). Setup and
day-to-day commands are in the [root README](../README.md).

## Layout

| Folder                         | What belongs there                                                    |
| ------------------------------ | --------------------------------------------------------------------- |
| [architecture/](architecture/) | How the system is built and why: pipeline, containers, filter design  |
| [datasets/](datasets/)         | One page per raw lake table (`lake.RAW.*`): source, columns, quirks   |
| [guides/](guides/)             | Task-oriented how-tos and runbooks (MCP setup, deployment, data coverage notes)             |
| [reports/](reports/)           | Dated issue audits and findings; Old Office of Engagement report examples in which this tool attempts to emulate automatically |


## Conventions

- File names are lowercase `snake_case.md`
  Dataset pages are named after the lake.RAW table: `docs/datasets/<table>.md`.
- Dated reports are prefixed with `YYYYMMDD`.
- Link repo files with relative paths so links work on GitHub and in an editor.
- Format with Prettier (`frontend/node_modules/.bin/prettier --write docs/**/*.md`).

## Dataset pages

Pages with a full column reference are marked ✅; the rest are placeholders
waiting for someone to fill in the table. Copy [zoning](datasets/zoning.md) 
to use as the dataset documentation template.

| Table                                                    | Status |
| -------------------------------------------------------- | ------ |
| [`zoning`](datasets/zoning.md)                           | ✅     |
| [`ambulance`](datasets/ambulance.md)                     | ⬜     |
| [`cdc_places_tract`](datasets/cdc_places_tract.md)       | ⬜     |
| [`flood`](datasets/flood.md)                             | ⬜     |
| [`historic_population`](datasets/historic_population.md) | ⬜     |
| [`housing`](datasets/housing.md)                         | ⬜     |
| [`qcew`](datasets/qcew.md)                               | ⬜     |
| [`vt_town_lines`](datasets/vt_town_lines.md)             | ⬜     |
| [`ww_service_areas`](datasets/ww_service_areas.md)       | ⬜     |
