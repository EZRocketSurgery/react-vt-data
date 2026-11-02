'use client';

import { useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import {
  Alert,
  Badge,
  Box,
  Center,
  Container,
  Group,
  Loader,
  MultiSelect,
  Paper,
  Select,
  SimpleGrid,
  Stack,
  Text,
  Title,
} from '@mantine/core';
import { ChartBarIcon, InfoIcon, WarningIcon } from '@phosphor-icons/react';
import { BASE_API_URL } from '@/config';
import { ChartStack } from '@/components/Charts';
import { createChartItem } from '@/utils/itemFactory';
import county_town_names from '@/data/county_town_names.json';
import { DataRow } from '@/types/cachedCharts';
import { Interest } from '@/components/profile/profileStore';
import { COLORS, FONTS } from '@/app/theme';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface IndicatorOption {
  key: string;
  label: string;
  topic: string;
  description: string;
  units: string;
  available: boolean;
}

interface ComparisonRow {
  place: string;
  geo_type: 'county' | 'state' | 'national';
  year: number;
  value: number;
}

interface ComparisonMeta {
  label: string;
  topic: string;
  description: string;
  units: string;
  source: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const COUNTIES = Object.keys(county_town_names);

const DEFAULT_INDICATOR = 'edu_bachelors_or_higher';

// Theme colors, matching the app's other charts: amber is the comparison
// accent (as in the Census Variable Comparison), spruce and TrendCharts'
// compare blue the benchmarks (slate was too close to spruce to tell apart),
// and the muted blue-grey of TrendCharts' compare lines the rest.
const BAR_COLORS = {
  highlight: COLORS.amber,
  state: COLORS.spruce,
  national: '#1c7ed6',
  other: '#b3c0cc',
};

// The profile interest (INTEREST_OPTIONS) each topic falls under. AddChart
// hides the Add button when a chart's categories match none of the user's
// interests, so the raw topic names can't be used as categories.
const TOPIC_INTERESTS: Record<string, Interest> = {
  'Educational attainment': 'Education',
  Income: 'Labor & Economy',
  Unemployment: 'Labor & Economy',
  Poverty: 'Labor & Economy',
  Disability: 'Demographics',
};

const LEGEND = [
  { label: 'Highlighted counties', color: BAR_COLORS.highlight },
  { label: 'Vermont', color: BAR_COLORS.state },
  { label: 'United States', color: BAR_COLORS.national },
  { label: 'Other counties', color: BAR_COLORS.other },
];

// ---------------------------------------------------------------------------
// Shared styling
// ---------------------------------------------------------------------------

const panelStyle = {
  borderColor: COLORS.line,
  backgroundColor: '#fff',
};

const selectStyles = {
  label: {
    fontFamily: FONTS.body,
    marginBottom: 6,
    color: COLORS.slate,
    fontWeight: 600,
  },
  input: { borderRadius: 8 },
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Topics in list order; a topic with nothing built yet is "coming soon". */
const topicData = (options: IndicatorOption[]) =>
  Array.from(new Set(options.map((o) => o.topic))).map((topic) => {
    const built = options.some((o) => o.topic === topic && o.available);
    return {
      value: topic,
      label: built ? topic : `${topic} (coming soon)`,
      disabled: !built,
    };
  });

const barColor = (row: ComparisonRow, highlighted: string[]) => {
  if (row.geo_type === 'state') return BAR_COLORS.state;
  if (row.geo_type === 'national') return BAR_COLORS.national;
  return highlighted.includes(row.place)
    ? BAR_COLORS.highlight
    : BAR_COLORS.other;
};

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function CountyComparisonPage() {
  const [options, setOptions] = useState<IndicatorOption[]>([]);
  const [indicator, setIndicator] = useState<string>(DEFAULT_INDICATOR);
  const topic = options.find((o) => o.key === indicator)?.topic ?? null;
  const topicVariables = options.filter(
    (o) => o.topic === topic && o.available,
  );
  const [rows, setRows] = useState<ComparisonRow[]>([]);
  const [meta, setMeta] = useState<ComparisonMeta | null>(null);
  const [year, setYear] = useState<number | null>(null);
  const [highlighted, setHighlighted] = useState<string[]>([]);
  // The indicator the current rows (or data error) belong to; anything else
  // means a request for the picked indicator is still in flight.
  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  const [optionsError, setOptionsError] = useState(false);
  const [dataError, setDataError] = useState(false);
  const loading = loadedFor !== indicator;

  useEffect(() => {
    axios
      .get(`${BASE_API_URL}/load/acs5-db/county-comparison/indicators`)
      .then((res) => setOptions(res.data.data))
      .catch(() => setOptionsError(true));
  }, []);

  useEffect(() => {
    // Set by the cleanup when the indicator changes again, so a slower
    // response for an earlier pick can't overwrite the newer one.
    let stale = false;
    axios
      .post(`${BASE_API_URL}/load/acs5-db/county-comparison`, { indicator })
      .then((res) => {
        if (stale) return;
        const data: ComparisonRow[] = res.data.data;
        setRows(data);
        setMeta(res.data.metadata);
        setDataError(false);
        // Keep the chosen year if the new variable has it, else the latest.
        const years = data.map((r) => r.year);
        setYear((y) => {
          if (y != null && years.includes(y)) return y;
          return years.length > 0 ? Math.max(...years) : null;
        });
      })
      .catch(() => {
        if (stale) return;
        setRows([]);
        setMeta(null);
        setDataError(true);
      })
      .finally(() => {
        if (!stale) setLoadedFor(indicator);
      });
    return () => {
      stale = true;
    };
  }, [indicator]);

  const error = optionsError
    ? 'Could not load the list of variables.'
    : !loading && dataError
      ? 'Could not load data for this variable.'
      : null;

  const years = useMemo(
    () => Array.from(new Set(rows.map((r) => r.year))).sort((a, b) => b - a),
    [rows],
  );

  const chartData: DataRow[] = useMemo(
    () =>
      rows
        .filter((r) => r.year === year)
        .sort((a, b) => a.value - b.value)
        .map((r) => ({
          place: r.place,
          value: r.value,
          color: barColor(r, highlighted),
        })),
    [rows, year, highlighted],
  );

  // Memoized with an id fixed per variable and year: ChartStack keys the card
  // on it and AddChart uses it to tell whether the chart is in the report, so
  // a fresh random id each render would remount the card and allow duplicates.
  const chartItem = useMemo(
    () => ({
      ...createChartItem({
        title: meta?.description ?? '',
        description: `${meta?.label ?? ''}, Vermont counties (${year ?? ''})`,
        xField: 'place',
        yField: 'value',
        subtype: 'RankedBarChart',
        data: chartData,
        categories: [(meta && TOPIC_INTERESTS[meta.topic]) ?? 'Demographics'],
        metadata: { source: meta?.source },
        chartParams: {
          color: 'color',
          unit: meta?.units,
          yLabel: meta?.label,
        },
      }),
      id: `county-comparison-${indicator}-${year ?? ''}`,
    }),
    [meta, year, chartData, indicator],
  );

  return (
    <Box style={{ backgroundColor: COLORS.birch, minHeight: '100vh' }}>
      {/* Compact themed header */}
      <Box
        pt={{ base: 44, sm: 56 }}
        pb={{ base: 28, sm: 36 }}
        style={{ borderBottom: `1px solid ${COLORS.line}` }}
      >
        <Container size="md">
          <Stack gap={8} align="center">
            <Text
              style={{
                fontFamily: FONTS.mono,
                fontSize: 12,
                letterSpacing: '0.14em',
                textTransform: 'uppercase',
                color: COLORS.slate,
              }}
            >
              Compare · All 14 Counties
            </Text>
            <Group gap="sm" justify="center">
              <Title
                order={2}
                style={{
                  fontFamily: FONTS.display,
                  fontWeight: 600,
                  color: COLORS.spruce,
                }}
              >
                Statewide County Comparison
              </Title>
              <Badge
                style={{
                  color: COLORS.birch,
                  background: COLORS.amber,
                  fontFamily: FONTS.mono,
                }}
              >
                Beta
              </Badge>
            </Group>
            <Text c="dimmed" size="sm" maw={560} ta="center">
              Pick a variable to see every Vermont county side by side, with
              Vermont and the United States for reference. Highlight the
              counties you care about to see how they compare to the rest of the
              state.
            </Text>
          </Stack>
        </Container>
      </Box>

      <Container size="lg" py={{ base: 32, sm: 44 }}>
        <Stack gap="xl">
          <Paper withBorder radius="lg" p="lg" style={panelStyle}>
            <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="md">
              <Select
                label="Topic"
                value={topic}
                onChange={(t) => {
                  // A new topic starts on its first variable.
                  const first = options.find(
                    (o) => o.topic === t && o.available,
                  );
                  if (first) setIndicator(first.key);
                }}
                data={topicData(options)}
                allowDeselect={false}
                size="md"
                styles={selectStyles}
              />
              <Select
                label="Variable"
                value={indicator}
                onChange={(v) => v && setIndicator(v)}
                data={topicVariables.map((o) => ({
                  value: o.key,
                  label: o.label,
                }))}
                searchable
                allowDeselect={false}
                size="md"
                styles={selectStyles}
              />
              <Select
                label="Year"
                value={year != null ? String(year) : null}
                onChange={(v) => v && setYear(Number(v))}
                data={years.map(String)}
                allowDeselect={false}
                size="md"
                styles={selectStyles}
              />
            </SimpleGrid>
            <MultiSelect
              label="Highlight counties"
              value={highlighted}
              onChange={setHighlighted}
              data={COUNTIES}
              placeholder={highlighted.length ? undefined : 'Pick counties…'}
              searchable
              clearable
              size="md"
              styles={selectStyles}
              mt="md"
            />
          </Paper>

          {error && (
            <Alert color="red" icon={<WarningIcon size={18} />}>
              {error}
            </Alert>
          )}

          {loading ? (
            <Center py="xl">
              <Loader color={COLORS.spruce} />
            </Center>
          ) : (
            chartData.length > 0 && (
              <Paper withBorder radius="lg" p="lg" style={panelStyle}>
                <Group justify="space-between" mb="sm" wrap="wrap">
                  <Group gap={8}>
                    <ChartBarIcon
                      size={18}
                      color={COLORS.spruce}
                      weight="duotone"
                    />
                    <Text
                      fw={700}
                      style={{
                        fontFamily: FONTS.display,
                        color: COLORS.spruce,
                      }}
                    >
                      Ranked, Lowest to Highest
                    </Text>
                  </Group>
                  <Group gap="md">
                    {LEGEND.map((l) => (
                      <Group key={l.label} gap={6}>
                        <Box
                          w={12}
                          h={12}
                          style={{ backgroundColor: l.color, borderRadius: 2 }}
                        />
                        <Text size="xs" c="dimmed">
                          {l.label}
                        </Text>
                      </Group>
                    ))}
                  </Group>
                </Group>
                <ChartStack charts={[chartItem]} action="add" />
                <Group gap={6} mt="sm" wrap="nowrap" align="flex-start">
                  <InfoIcon size={14} color={COLORS.slate} />
                  <Text size="xs" c="dimmed">
                    Values are Census survey estimates and have a margin of
                    error. Small counties such as Essex and Grand Isle have the
                    widest margins, so small differences between counties may
                    not be meaningful.
                  </Text>
                </Group>
              </Paper>
            )
          )}
        </Stack>
      </Container>
    </Box>
  );
}
