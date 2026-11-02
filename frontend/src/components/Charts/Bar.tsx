import { useMemo, useEffect } from 'react';

// recharts
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  Cell,
  LabelList,
} from 'recharts';
import * as d3 from 'd3';

// chartjs
import { Bar as BarJS } from 'react-chartjs-2';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  BarElement,
  Tooltip as TooltipJS,
  Legend as LegendJS,
  TooltipItem,
  ChartEvent,
  LegendItem,
  LegendElement,
} from 'chart.js';
ChartJS.register(CategoryScale, LinearScale, BarElement, TooltipJS, LegendJS);

import { ChartItem, DataRow } from '@/types/cachedCharts';
import { usePdfMode } from '@/contexts/PdfModeContext';
import {
  Box,
  Group,
  Text,
  ActionIcon,
  Tooltip as MantineTooltip,
} from '@mantine/core';
import { IconInfoCircle } from '@tabler/icons-react';

// d3 color schemes looked up by name (e.g. 'schemeCategory10')
const d3Schemes = d3 as unknown as Record<string, readonly string[]>;

// Chart items are rebuilt on every page render (fresh object, fresh
// chartParams, and a fresh `[]` for data that hasn't loaded), so the Chart.js
// memos below key on the data arrays and primitive params instead of `chart`.
// A new `data`/`options` object makes react-chartjs-2 call chart.update(),
// which replays the animation.
const EMPTY_ROWS: DataRow[] = [];
const stableRows = (rows?: DataRow[]) => (rows?.length ? rows : EMPTY_ROWS);

const SamePerXBarChart = ({
  chart,
  view,
}: {
  chart: ChartItem<DataRow>;
  view?: 'gallery' | 'report';
}) => {
  const isPdfMode = usePdfMode();
  return (
    <Box style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <Group gap={4}>
        <Text size="sm" fw={600}>
          {chart.title}
        </Text>
        {chart.description && (
          <MantineTooltip label={chart.description} multiline w={240}>
            <ActionIcon variant="subtle" size="sm">
              <IconInfoCircle size={14} />
            </ActionIcon>
          </MantineTooltip>
        )}
      </Group>
      <Box style={{ flex: 1, minHeight: 0 }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={chart.data}
            margin={{ top: 5, right: 30, left: 20, bottom: 5 }}
          >
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis
              dataKey={chart.xField}
              interval={chart.chartParams?.xInterval ?? 0}
              tickFormatter={(value) =>
                String(value)
                  .toLowerCase()
                  .replace(/\b\w/g, (char) => char.toUpperCase())
              }
              angle={chart.chartParams?.xAngle ?? -40}
              textAnchor={chart.chartParams?.xAngle ? 'end' : 'middle'}
              height={chart.chartParams?.xHeight ?? 70}
            />
            <YAxis />
            <Tooltip />
            <Legend />
            {chart.chartParams?.datakeys?.map(([datakey, color]) => (
              <Bar
                key={datakey}
                dataKey={datakey}
                fill={color}
                isAnimationActive={view !== 'gallery' && !isPdfMode}
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </Box>
    </Box>
  );
};

// ---------------------------------------------------------------------------
// DiffPerXBarChart — single dataset, per-bar colors from data
// ---------------------------------------------------------------------------

/** SVG (Recharts) version used when rendering to PDF. */
const DiffPerXBarChartSVG = ({ chart }: { chart: ChartItem<DataRow> }) => {
  const colors = chart.data.map(
    (entry) => entry[chart.chartParams!.color!] as string,
  );
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart
        data={chart.data}
        margin={{ top: 5, right: 30, left: 20, bottom: 5 }}
      >
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey={chart.xField} />
        <YAxis />
        <Tooltip />
        <Bar dataKey={chart.yField}>
          {chart.data.map((_, index) => (
            <Cell key={index} fill={colors[index]} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
};

const DiffPerXBarChart = ({
  chart,
  view,
}: {
  chart: ChartItem<DataRow>;
  view?: 'gallery' | 'report';
}) => {
  const isPdfMode = usePdfMode();

  const rows = stableRows(chart.data);
  const { xField, yField } = chart;
  const colorField = chart.chartParams!.color!;
  const data = useMemo(
    () => ({
      labels: rows.map((entry) => entry[xField]),
      datasets: [
        {
          label: yField,
          data: rows.map((entry) => entry[yField] as number),
          backgroundColor: rows.map((entry) => entry[colorField] as string),
        },
      ],
    }),
    [rows, xField, yField, colorField],
  );

  const options = useMemo(
    () => ({
      responsive: true,
      maintainAspectRatio: false,
      // Gallery charts update as other requests finish; never animate those updates.
      animation: view === 'gallery' ? (false as const) : undefined,
      plugins: {
        legend: { display: false },
        tooltip: { enabled: true },
      },
    }),
    [view],
  );

  if (isPdfMode) return <DiffPerXBarChartSVG chart={chart} />;

  return <BarJS data={data} options={options} />;
};

// ---------------------------------------------------------------------------
// CompareDiffPerXBarChart — two datasets, primary with per-bar colors
// ---------------------------------------------------------------------------

interface CompareDiffChartItem extends ChartItem<DataRow> {
  compareData: DataRow[];
  chartParams: {
    color?: string;
    legendLabels?: [string, string];
    colorScheme?: string;
    fixedYear?: number;
    percentFormat?: boolean;
    includeCategories?: string[];
    unit?: string;
    yLabel?: string;
  };
}

/** Reorder compare rows to match the main rows by x value (missing -> no y). */
const alignByX = (main: DataRow[], cmp: DataRow[], xField: string) => {
  const byX = new Map(cmp.map((r) => [r[xField], r]));
  return main.map((r) => byX.get(r[xField]) ?? { [xField]: r[xField] });
};

/** SVG (Recharts) version used when rendering to PDF. */
const CompareDiffPerXBarChartSVG = ({
  chart,
}: {
  chart: CompareDiffChartItem;
}) => {
  const legendLabels = chart.chartParams.legendLabels ?? [
    chart.yField,
    `${chart.yField} (compare)`,
  ];

  const includeCategories = chart.chartParams?.includeCategories;
  const filteredData = includeCategories
    ? chart.data.filter((entry) =>
        includeCategories.includes(entry[chart.xField] as string),
      )
    : chart.data;
  const filteredCompareData = alignByX(
    filteredData,
    includeCategories && chart.compareData
      ? chart.compareData.filter((entry) =>
          includeCategories.includes(entry[chart.xField] as string),
        )
      : (chart.compareData ?? []),
    chart.xField,
  );

  // Determine per-bar primary colors (same logic as Chart.js version)
  let colors: string[];
  if (chart.chartParams?.color && filteredData[0]?.[chart.chartParams.color]) {
    colors = filteredData.map(
      (entry) => entry[chart.chartParams.color!] as string,
    );
  } else {
    const schemeName = chart.chartParams?.colorScheme ?? 'schemeCategory10';
    const colorScale = d3.scaleOrdinal<string, string>(d3Schemes[schemeName]);
    colors = filteredData.map((_, i) => colorScale(i.toString()));
  }

  // Merge primary + compare into one array for grouped bars
  const merged = filteredData.map((entry, i) => ({
    [chart.xField]: entry[chart.xField],
    primary: entry[chart.yField],
    compare: filteredCompareData[i]?.[chart.yField] ?? null,
  }));

  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart
        data={merged}
        margin={{ top: 5, right: 30, left: 20, bottom: 5 }}
      >
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey={chart.xField} />
        <YAxis
          label={
            chart.chartParams.yLabel
              ? {
                  value: chart.chartParams.yLabel,
                  angle: -90,
                  position: 'insideLeft',
                }
              : undefined
          }
        />
        <Tooltip />
        <Legend />
        <Bar dataKey="primary" name={legendLabels[0]}>
          {merged.map((_, i) => (
            <Cell key={i} fill={colors[i]} />
          ))}
        </Bar>
        <Bar dataKey="compare" name={legendLabels[1]} fill="#999" />
      </BarChart>
    </ResponsiveContainer>
  );
};

const CompareDiffPerXBarChart = ({
  chart,
  view,
  onPlotData,
}: {
  chart: CompareDiffChartItem;
  view?: 'gallery' | 'report';
  onPlotData?: (rows: DataRow[]) => void;
}) => {
  const isPdfMode = usePdfMode();

  const includeCategories = chart.chartParams?.includeCategories;
  const rows = stableRows(chart.data);
  const compareRows = stableRows(chart.compareData);

  // Filter primary dataset based on categories if specified
  const filteredData = useMemo(() => {
    return includeCategories
      ? rows.filter((entry) =>
          includeCategories.includes(entry[chart.xField] as string),
        )
      : rows;
  }, [rows, includeCategories, chart.xField]);

  // Filter comparison dataset based on categories if specified
  const filteredCompareData = useMemo(() => {
    const cmp = includeCategories
      ? compareRows.filter((entry) =>
          includeCategories.includes(entry[chart.xField] as string),
        )
      : compareRows;
    return cmp.length ? alignByX(filteredData, cmp, chart.xField) : cmp;
  }, [compareRows, filteredData, includeCategories, chart.xField]);

  // Derive exact plottable rows and report back to ChartCard for TableView
  const plotData = useMemo(() => {
    return filteredData.map((entry, i) => {
      const cmpEntry = filteredCompareData[i];
      return {
        [chart.xField]: entry[chart.xField],
        [chart.yField]: entry[chart.yField],
        ...(cmpEntry
          ? { [`${chart.yField} (cmp)`]: cmpEntry[chart.yField] }
          : {}),
      };
    });
  }, [filteredData, filteredCompareData, chart.xField, chart.yField]);

  useEffect(() => {
    onPlotData?.(plotData);
  }, [plotData, onPlotData]);

  const { xField, yField } = chart;
  const colorField = chart.chartParams?.color;
  const colorScheme = chart.chartParams?.colorScheme || 'schemeTableau10';
  const primaryLabel = chart.chartParams?.legendLabels?.[0] ?? yField;
  const compareLabel =
    chart.chartParams?.legendLabels?.[1] ?? `${yField} (compare)`;

  const data = useMemo(() => {
    let colors: string[];
    if (colorField && rows[0]?.[colorField]) {
      colors = filteredData.map((entry) => entry[colorField] as string);
    } else {
      const colorScale = d3.scaleOrdinal<string, string>(
        d3Schemes[colorScheme],
      );
      colors = filteredData.map((_, index) => colorScale(index.toString()));
    }

    return {
      labels: filteredData.map((entry) => entry[xField]),
      datasets: [
        {
          label: primaryLabel,
          data: filteredData.map((entry) => entry[yField] as number),
          backgroundColor: colors,
        },
        {
          label: compareLabel,
          data: filteredCompareData.map((entry) => entry[yField] as number),
          backgroundColor: filteredCompareData.map(() => '#D3D3D3'),
        },
      ],
    };
  }, [
    rows,
    filteredData,
    filteredCompareData,
    xField,
    yField,
    colorField,
    colorScheme,
    primaryLabel,
    compareLabel,
  ]);

  const percentFormat = chart.chartParams?.percentFormat ?? false;
  const yLabel = chart.chartParams?.yLabel;
  const options = useMemo(
    () => ({
      responsive: true,
      maintainAspectRatio: false,
      animation: view === 'gallery' ? (false as const) : undefined,
      plugins: {
        legend: { display: true },
        tooltip: {
          callbacks: {
            label: (context: TooltipItem<'bar'>) => {
              const value = context.parsed.y ?? 0;
              return percentFormat ? `${value}%` : value.toLocaleString();
            },
          },
        },
      },
      scales: {
        y: {
          title: { display: !!yLabel, text: yLabel },
          ticks: {
            callback: (value: string | number) =>
              percentFormat ? `${value}%` : value.toLocaleString(),
          },
        },
      },
    }),
    [view, percentFormat, yLabel],
  );

  if (isPdfMode) return <CompareDiffPerXBarChartSVG chart={chart} />;

  return <BarJS data={data} options={options} />;
};

type AllowanceRow = {
  use_type: string;
  val: string;
  Acres: number;
};

const VAL_GROUPS: Record<string, string> = {
  True: 'Allowed',
  False: 'Prohibited',
  'Public Hearing': 'May be Allowed',
  'Allowed/Conditional': 'May be Allowed',
  Overlay: 'May be Allowed',
  'Not Mentioned': 'Not Mentioned',
};

const VAL_GROUP_COLORS: Record<string, string> = {
  Allowed: '#274c77',
  'May be Allowed': '#6096ba',
  Prohibited: '#e07a5f',
  'Not Mentioned': '#c8d3d5',
};

const USE_TYPE_ORDER = [
  '1 Family',
  '2 Family',
  '3 Family',
  '4 Family',
  // "Acessory Dwelling Unit", // NOTE: matches the typo in the source data ("Acessory")
  // "Planned Unit Development",
  // "Planned Residential Development",
];

const INCLUDED_USE_TYPES = new Set([
  '1_Family',
  '2_Family',
  '3_Family',
  '4_Family',
]);

const sortUseTypes = (types: string[]) => {
  return [...types].sort((a, b) => {
    const ai = USE_TYPE_ORDER.indexOf(a);
    const bi = USE_TYPE_ORDER.indexOf(b);
    if (ai === -1 && bi === -1) return a.localeCompare(b);
    if (ai === -1) return 1;
    if (bi === -1) return -1;
    return ai - bi;
  });
};

const groupVal = (val: string) => VAL_GROUPS[val] ?? val;
const VAL_ORDER = ['Allowed', 'May be Allowed', 'Prohibited', 'Not Mentioned'];

const cleanUseType = (useType: string) => useType.replace(/_/g, ' ');

type PivotRow = { use_type: string } & Record<string, number | string>;
const pivot = (rows: AllowanceRow[]): Record<string, PivotRow> => {
  const map: Record<string, PivotRow> = {};
  for (const r of rows) {
    const useType = cleanUseType(r.use_type);
    const group = groupVal(r.val);
    if (!map[useType]) map[useType] = { use_type: useType };
    map[useType][group] =
      ((map[useType][group] as number) || 0) + (Number(r.Acres) || 0);
  }
  return map;
};

// Module-level so they're stable references in the useMemo deps below.
const colorForGroup = (group: string) => VAL_GROUP_COLORS[group] ?? '#999999';

const mutedColor = (hex: string) => {
  const { r, g, b } = d3.rgb(hex);
  return `rgba(${r}, ${g}, ${b}, 0.45)`;
};

const ZoningAllowanceStackedBarChart = ({
  chart,
  view,
  onPlotData,
}: {
  chart: CompareDiffChartItem;
  view?: 'gallery' | 'report';
  onPlotData?: (rows: DataRow[]) => void;
}) => {
  // const isPdfMode = usePdfMode();
  // if (isPdfMode) return <ZoningAllowanceStackedBarChartSVG chart={chart} />;

  const rawMain = stableRows(chart.data);
  const rawCompare = stableRows(chart.compareData);

  const mainRows = useMemo(
    () =>
      (rawMain as unknown as AllowanceRow[]).filter((r) =>
        INCLUDED_USE_TYPES.has(r.use_type),
      ),
    [rawMain],
  );

  const compareRows = useMemo(
    () =>
      (rawCompare as unknown as AllowanceRow[]).filter((r) =>
        INCLUDED_USE_TYPES.has(r.use_type),
      ),
    [rawCompare],
  );

  const main = useMemo(() => pivot(mainRows), [mainRows]);
  const compare = useMemo(() => pivot(compareRows), [compareRows]);

  const labels = useMemo(
    () =>
      sortUseTypes(
        Array.from(new Set([...Object.keys(main), ...Object.keys(compare)])),
      ),
    [main, compare],
  );

  const stackKeys = VAL_ORDER;

  const plotData = useMemo(() => {
    return labels.map((useType) => {
      const row: DataRow = { 'Residential Type': useType };

      stackKeys.forEach((key) => {
        row[key] = main[useType]?.[key] ?? 0;
      });

      if (Object.keys(compare).length > 0) {
        stackKeys.forEach((key) => {
          row[`${key} (cmp)`] = compare[useType]?.[key] ?? 0;
        });
      }

      return row;
    });
  }, [labels, main, compare, stackKeys]);

  // 3. Serialize plotData in the dependency array to break reference-equality loops!
  const serializedPlotData = JSON.stringify(plotData);

  useEffect(() => {
    onPlotData?.(plotData);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serializedPlotData, onPlotData]);

  const datasets = useMemo(
    () => [
      ...stackKeys.map((key) => ({
        label: `${key}`,
        data: labels.map((l) => main[l]?.[key] || 0),
        stack: 'main',
        backgroundColor: colorForGroup(key),
      })),

      ...stackKeys.map((key) => ({
        label: `${key}`,
        data: labels.map((l) => compare[l]?.[key] || 0),
        stack: 'compare',
        backgroundColor: mutedColor(colorForGroup(key)),
        borderColor: colorForGroup(key),
        borderWidth: 1,
      })),
    ],
    [stackKeys, labels, main, compare],
  );

  const data = useMemo(
    () => ({
      labels,
      datasets,
    }),
    [labels, datasets],
  );

  const options = useMemo(
    () => ({
      responsive: true,
      maintainAspectRatio: false,
      animation: view === 'gallery' ? (false as const) : { duration: 250 },
      transitions: {
        active: {
          animation: {
            duration: 0, // Disables jerky animation when hovering over bars
          },
        },
      },
      plugins: {
        legend: {
          display: true,
          labels: {
            generateLabels: (chart: ChartJS) =>
              stackKeys.map((key) => {
                const mainIndex = chart.data.datasets.findIndex(
                  (ds) => ds.label === `${key}`,
                );
                const compareIndex = chart.data.datasets.findIndex(
                  (ds) => ds.label === `${key}`,
                );

                const mainMeta = chart.getDatasetMeta(mainIndex);
                const compareMeta = chart.getDatasetMeta(compareIndex);

                const hidden =
                  (mainMeta.hidden ?? chart.data.datasets[mainIndex].hidden) &&
                  (compareMeta.hidden ??
                    chart.data.datasets[compareIndex].hidden);

                return {
                  text: key,
                  fillStyle: colorForGroup(key),
                  strokeStyle: colorForGroup(key),
                  lineWidth: 1,
                  hidden,
                  datasetIndex: mainIndex,
                };
              }),
          },
          onClick: (
            _e: ChartEvent,
            legendItem: LegendItem,
            legend: LegendElement<'bar'>,
          ) => {
            const chart = legend.chart;
            const key = legendItem.text;

            chart.data.datasets.forEach((ds, idx) => {
              if (ds.label?.startsWith(key)) {
                const meta = chart.getDatasetMeta(idx);
                meta.hidden = !(meta.hidden ?? false);
              }
            });

            chart.update();
          },
        },
        tooltip: {
          callbacks: {
            label: (ctx: TooltipItem<'bar'>) =>
              `${ctx.dataset.label}: ${(ctx.raw as number | undefined)?.toLocaleString() ?? ctx.raw}`,
          },
        },
      },
      scales: {
        x: { stacked: true },
        y: { stacked: true },
      },
    }),
    [stackKeys, view],
  );

  return <BarJS data={data} options={options} />;
};

// ---------------------------------------------------------------------------
// CompareHBarChart — horizontal grouped bars
// ---------------------------------------------------------------------------

/**
 * Horizontal grouped bar chart for head-to-head location comparison.
 * data entries:        [{ [xField]: variableName, [yField]: primaryValue }]
 * compareData entries: [{ [xField]: variableName, [yField]: compareValue }]
 * chartParams.unit:    optional suffix appended to tooltip values (e.g. '%')
 *
 * Extensible to multiple variables: just add more entries to both arrays.
 */

/** SVG (Recharts) version used when rendering to PDF. */
const CompareHBarChartSVG = ({ chart }: { chart: CompareDiffChartItem }) => {
  const legendLabels = chart.chartParams?.legendLabels ?? [
    'Primary',
    'Comparison',
  ];
  const unit = chart.chartParams?.unit ?? '';

  const merged = chart.data.map((entry, i) => ({
    name: entry[chart.xField],
    [legendLabels[0]]: entry[chart.yField],
    [legendLabels[1]]: chart.compareData?.[i]?.[chart.yField] ?? null,
  }));

  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart
        data={merged}
        layout="vertical"
        margin={{ top: 5, right: 40, left: 10, bottom: 5 }}
      >
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis type="number" tickFormatter={(v) => `${v}${unit}`} />
        <YAxis
          type="category"
          dataKey="name"
          width={120}
          tick={{ fontSize: 11 }}
        />
        <Tooltip formatter={(v) => `${v}${unit}`} />
        <Legend />
        <Bar dataKey={legendLabels[0]} fill="#154734" />
        <Bar dataKey={legendLabels[1]} fill="#8899aa" />
      </BarChart>
    </ResponsiveContainer>
  );
};

const CompareHBarChart = ({
  chart,
  view,
}: {
  chart: CompareDiffChartItem;
  view?: 'gallery' | 'report';
}) => {
  const isPdfMode = usePdfMode();
  const unit = chart.chartParams?.unit ?? '';

  const rows = stableRows(chart.data);
  const compareRows = stableRows(chart.compareData);
  const { xField, yField } = chart;
  const primaryLabel = chart.chartParams?.legendLabels?.[0] ?? 'Primary';
  const compareLabel = chart.chartParams?.legendLabels?.[1] ?? 'Comparison';

  const data = useMemo(
    () => ({
      labels: rows.map((entry) => entry[xField]),
      datasets: [
        {
          label: primaryLabel,
          data: rows.map((entry) => entry[yField] as number),
          backgroundColor: '#154734',
        },
        {
          label: compareLabel,
          data: compareRows.map((entry) => entry[yField] as number),
          backgroundColor: '#8899aa',
        },
      ],
    }),
    [rows, compareRows, xField, yField, primaryLabel, compareLabel],
  );

  const options = useMemo(
    () => ({
      indexAxis: 'y' as const,
      responsive: true,
      maintainAspectRatio: false,
      animation: view === 'gallery' ? (false as const) : undefined,
      plugins: {
        legend: { display: true },
        tooltip: {
          callbacks: {
            label: (ctx: TooltipItem<'bar'>) =>
              `${ctx.dataset.label}: ${ctx.raw}${unit}`,
          },
        },
      },
      scales: {
        x: {
          ticks: {
            callback: (value: number | string) => `${value}${unit}`,
          },
        },
      },
    }),
    [view, unit],
  );

  if (isPdfMode) return <CompareHBarChartSVG chart={chart} />;

  return <BarJS data={data} options={options} />;
};

// ---------------------------------------------------------------------------
// RankedBarChart — one bar per place, sorted, each bar its own color, value
// printed on top. Built for side-by-side county comparisons that get
// screenshotted into slides.
// data:                [{<xField>, <yField>, <color field>}], already sorted
// chartParams.color:   field holding each bar's color
// chartParams.unit:    'percent' adds a %; 'dollars' adds a $, shortened to
//                      thousands ($59.3k) on bars and the axis so 16 labels fit
// chartParams.yLabel:  column name for the value in the table view
// ---------------------------------------------------------------------------

const RankedBarChart = ({
  chart,
  view,
  onPlotData,
}: {
  chart: ChartItem<DataRow>;
  view?: 'gallery' | 'report';
  onPlotData?: (rows: DataRow[]) => void;
}) => {
  const isPdfMode = usePdfMode();
  const rows = stableRows(chart.data);
  const { xField, yField } = chart;
  const colorField = chart.chartParams?.color ?? 'color';
  const unit = chart.chartParams?.unit;
  const yLabel = (chart.chartParams?.yLabel as string | undefined) ?? yField;
  const fmt = (v: unknown, short = false) => {
    if (v == null) return '';
    const n = Number(v);
    if (unit === 'dollars')
      return short
        ? `$${(n / 1000).toLocaleString(undefined, { maximumFractionDigits: 1 })}k`
        : `$${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
    const num = n.toLocaleString(undefined, { maximumFractionDigits: 1 });
    return unit === 'percent' ? `${num}%` : num;
  };
  const fmtShort = (v: unknown) => fmt(v, true);

  // The table view shows place and value only, not the bar colors.
  useEffect(() => {
    onPlotData?.(rows.map((r) => ({ Place: r[xField], [yLabel]: r[yField] })));
  }, [rows, xField, yField, yLabel, onPlotData]);

  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={rows} margin={{ top: 24, right: 10, left: 0, bottom: 5 }}>
        <CartesianGrid
          strokeDasharray="3 3"
          stroke="#e0d8cc"
          vertical={false}
        />
        <XAxis
          dataKey={xField}
          interval={0}
          angle={-40}
          textAnchor="end"
          height={90}
          tick={{ fontSize: 12 }}
        />
        <YAxis tick={{ fontSize: 12 }} tickFormatter={fmtShort} />
        <Tooltip formatter={(v) => [fmt(v), yLabel]} />
        <Bar
          dataKey={yField}
          isAnimationActive={view !== 'gallery' && !isPdfMode}
        >
          {rows.map((r, i) => (
            <Cell key={i} fill={r[colorField] as string} />
          ))}
          <LabelList
            dataKey={yField}
            position="top"
            formatter={fmtShort}
            style={{ fontSize: 11, fontWeight: 600, fill: '#1B211D' }}
          />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
};

export {
  SamePerXBarChart,
  DiffPerXBarChart,
  CompareDiffPerXBarChart,
  CompareHBarChart,
  ZoningAllowanceStackedBarChart,
  RankedBarChart,
};
