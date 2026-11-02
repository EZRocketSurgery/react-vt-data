export { default as DualLine } from './DualLine';
export {
  SamePerXBarChart,
  DiffPerXBarChart,
  CompareDiffPerXBarChart,
  CompareHBarChart,
  ZoningAllowanceStackedBarChart,
  RankedBarChart,
} from './Bar';

export {
  renderTable,
  renderTableEstimates,
  renderTableMixed,
} from './DemographicsTable';
export {
  DemographicsTrendChart,
  PopulationTrendChart,
  HistoricPopulationChangeTrendChart,
  PopulationChangeTrendChart,
  MedianAgeTrendChart,
  EducationTrendChart,
  HomeValueTrendChart,
  HousingUnitsTrendChart,
  HousingTenureAreaChart,
  UnemploymentTrendChart,
  LaborForceTrendChart,
  LaborForceTrendChartPrimeAge,
  EarningsTrendChart,
  HouseholdIncomeTrendChart,
  PerCapitaIncomeTrendChart,
  HousingIncomeBurdenChart,
  DPTrendChart,
} from './TrendCharts';
export { EmploymentAreaChart } from './EmploymentAreaChart';
export { AgeAreaChart } from './AgeAreaChart';
export { AgentChart, renderTableAgent } from './AgentChart';

import { ChartItem, DataRow } from '@/types/cachedCharts';
import {
  Card,
  Box,
  Title,
  Stack,
  Text,
  Group,
  SimpleGrid,
  ActionIcon,
  Modal,
  TextInput,
  Textarea,
  Tooltip,
  Skeleton,
} from '@mantine/core';
import { useIntersection } from '@mantine/hooks';
import {
  CornersOutIcon,
  CornersInIcon,
  PencilSimpleIcon,
  DotsSixVerticalIcon,
  XIcon,
} from '@phosphor-icons/react';
import * as motion from 'motion/react-client';
import { AddChart, RemoveChart } from './saving';
import { useEffect, useRef, useState } from 'react';
import { TableView, ViewSwitch } from './TableView';
import { usePdfMode } from '@/contexts/PdfModeContext';
import { useItems } from '@/components/ItemsProvider';
import classes from './ChartCard.module.css';
import type {
  DraggableAttributes,
  DraggableSyntheticListeners,
} from '@dnd-kit/core';

// ChartCard
interface ChartCardProps<TData extends DataRow> {
  chart: ChartItem<TData>;
  ChartComponent: React.FC<{
    chart: ChartItem<TData>;
    view?: 'gallery' | 'report';
    onPlotData?: (rows: DataRow[]) => void;
  }>;
  TrendComponent?: React.FC<{
    chart: ChartItem<TData>;
    view?: 'gallery' | 'report';
    onPlotData?: (rows: DataRow[]) => void;
  }>;
  matchedCategories?: string[];
  action?: 'add' | 'remove' | 'toggle';
  defId?: string;
  isIncluded?: boolean;
  onToggle?: () => void;
  view?: 'gallery' | 'report';
  border?: boolean;
  dragHandleProps?: {
    attributes: DraggableAttributes;
    listeners: DraggableSyntheticListeners;
  };
}
export const ChartCard = <TData extends DataRow>({
  chart,
  ChartComponent,
  TrendComponent,
  matchedCategories = [],
  action = 'add',
  defId,
  isIncluded,
  onToggle,
  view = 'report',
  border = true,
  dragHandleProps,
}: ChartCardProps<TData>) => {
  const isPdfMode = usePdfMode();
  const isGallery = view === 'gallery';
  const showBorder = border === true;

  // Stable across renders even though chart.id is a fresh UUID every render
  // (auto-populated items are rebuilt from live data on each mount) — this is
  // the only safe key for persisted per-chart customization.
  const customizationId = defId ?? chart.id;
  const { chartCustomizations, setChartView, setChartTitle, setChartNotes } =
    useItems();
  const customization = chartCustomizations[customizationId];

  const isTablePrimary = chart.subtype.startsWith('renderTable');
  const [localView, setLocalViewState] = useState<'chart' | 'table'>(
    () => customization?.view ?? 'chart',
  );
  const setLocalView = (v: 'chart' | 'table') => {
    setLocalViewState(v);
    if (defId) setChartView(defId, v);
  };

  const [isEditingTitle, setIsEditingTitle] = useState(false);
  const [isEditingNotes, setIsEditingNotes] = useState(false);
  const displayTitle = customization?.title ?? chart.description;
  const displayNotes = customization?.notes ?? chart.notes;
  const canEdit = !isGallery && !isPdfMode && !!defId;

  const selfManagesViews = !!chart.chartParams?.noViewSwitch;

  const showViewSwitch =
    !selfManagesViews &&
    !isGallery &&
    (isTablePrimary ? !!TrendComponent : true);

  const [trendPlotData, setTrendPlotData] = useState<DataRow[] | undefined>();

  const PlotComponent = isTablePrimary ? TrendComponent : ChartComponent;

  const content =
    selfManagesViews || !PlotComponent ? (
      <ChartComponent chart={chart} view={view} />
    ) : (
      <>
        {/* Stays mounted (just hidden) while the table shows: it derives the
            rows the table displays via onPlotData. Unmounting it left a card
            that mounts straight into table view — e.g. a persisted view on a
            re-included chart — falling back to the raw long-format data. */}
        <Box className={classes.plotLayer} data-hidden={localView !== 'chart'}>
          <PlotComponent
            chart={chart}
            view={view}
            onPlotData={setTrendPlotData}
          />
        </Box>

        {localView === 'table' &&
          (isTablePrimary ? (
            <TableView chart={chart} rows={trendPlotData} />
          ) : (
            <Box h={400}>
              <TableView chart={chart} rows={trendPlotData} />
            </Box>
          ))}
      </>
    );

  // Report sections already group by category, so the interest highlight
  // only helps when browsing the gallery.
  const isHighlighted = isGallery && matchedCategories.length > 0;

  // Table-primary items showing their trend chart still need a definite
  // height in PDF mode — the chart's ResponsiveContainer is height="100%",
  // which collapses to 0 against an 'auto'-height ancestor. 'auto' is only
  // safe when a native table (which sizes to its own content) is showing.
  const showsTrendChart =
    isTablePrimary && localView === 'chart' && !!TrendComponent;

  const chartBoxHeight = isPdfMode
    ? isTablePrimary && !showsTrendChart
      ? 'auto'
      : 400
    : isGallery
      ? 275
      : 400;

  const [expanded, setExpanded] = useState(false);

  return (
    <>
      <Card
        shadow={showBorder ? 'sm' : undefined}
        padding={isGallery ? 'sm' : 'lg'}
        radius="md"
        withBorder={showBorder}
        className={isGallery ? classes.galleryCard : classes.reportCard}
        data-chart-id={customizationId}
        data-chart-subtype={chart.subtype}
        onClick={
          isGallery
            ? (e) => {
                e.stopPropagation();
                setExpanded((v) => !v);
              }
            : undefined
        }
        style={{
          ...(isHighlighted ? { borderColor: '#154734', borderWidth: 2 } : {}),
          breakInside: 'avoid',
          pageBreakInside: 'avoid',
        }}
      >
        <Box mb={isGallery ? 4 : 'xs'}>
          <Group gap={8} wrap="nowrap" mb={isGallery ? 4 : 8} w="100%">
            {dragHandleProps && !isPdfMode && (
              <ActionIcon
                variant="subtle"
                color="gray"
                size="sm"
                style={{ cursor: 'grab', touchAction: 'none' }}
                {...dragHandleProps.attributes}
                {...dragHandleProps.listeners}
              >
                <DotsSixVerticalIcon size={16} />
              </ActionIcon>
            )}
            {isEditingTitle ? (
              <TextInput
                autoFocus
                size="sm"
                defaultValue={displayTitle}
                onBlur={(e) => {
                  setChartTitle(defId!, e.currentTarget.value);
                  setIsEditingTitle(false);
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') e.currentTarget.blur();
                  if (e.key === 'Escape') setIsEditingTitle(false);
                }}
                style={{ flex: '0 1 auto' }}
              />
            ) : (
              <Title
                order={isGallery ? 5 : 4}
                fw={isGallery ? 500 : 600}
                lineClamp={1}
                onClick={canEdit ? () => setIsEditingTitle(true) : undefined}
                style={canEdit ? { cursor: 'text' } : undefined}
              >
                {displayTitle}
              </Title>
            )}
            {canEdit && !isEditingTitle && (
              <ActionIcon
                variant="subtle"
                color="gray"
                size="sm"
                onClick={() => setIsEditingTitle(true)}
                aria-label="Edit chart title"
                className={classes.hoverReveal}
              >
                <PencilSimpleIcon size={14} />
              </ActionIcon>
            )}
            <Box flex={1} />
            {isGallery && (
              <Group justify="flex-end">
                <ActionIcon
                  component={motion.button}
                  variant="transparent"
                  size="lg"
                  onClick={(e) => {
                    e.stopPropagation();
                    setExpanded((v) => !v);
                  }}
                  whileHover={{ scale: 1.15 }}
                  whileTap={{ scale: 0.9 }}
                >
                  {expanded ? (
                    <CornersInIcon size={50} weight="thin" color="grey" />
                  ) : (
                    <CornersOutIcon size={30} weight="thin" color="grey" />
                  )}
                </ActionIcon>
              </Group>
            )}

            {!isPdfMode && showViewSwitch && (
              <ViewSwitch view={localView} setView={setLocalView} />
            )}
            {!isPdfMode && !isGallery && action === 'toggle' && onToggle && (
              <Tooltip label="Remove from report">
                <ActionIcon
                  variant="subtle"
                  color="gray"
                  onClick={onToggle}
                  aria-label="Remove from report"
                >
                  <XIcon size={16} />
                </ActionIcon>
              </Tooltip>
            )}
          </Group>

          {!isGallery && (
            <Text size="sm" c="dimmed" mt={-4} mb={8}>
              {chart.title}
            </Text>
          )}

          {canEdit ? (
            isEditingNotes ? (
              <Textarea
                autoFocus
                size="xs"
                mb={8}
                placeholder="Add a note for this chart…"
                defaultValue={displayNotes ?? ''}
                onBlur={(e) => {
                  setChartNotes(defId!, e.currentTarget.value);
                  setIsEditingNotes(false);
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Escape') setIsEditingNotes(false);
                }}
              />
            ) : (
              <Text
                size="xs"
                c="dimmed"
                fs={displayNotes ? undefined : 'italic'}
                mb={8}
                onClick={() => setIsEditingNotes(true)}
                style={{ cursor: 'text' }}
              >
                {displayNotes || '+ Add note'}
              </Text>
            )
          ) : (
            displayNotes && (
              <Text
                size="xs"
                c="dimmed"
                mb={8}
                lineClamp={isGallery ? 2 : undefined}
              >
                {displayNotes}
              </Text>
            )
          )}
        </Box>

        <Box w="100%">
          <Box
            data-chart-box
            className={classes.chartBox}
            style={{
              height: chartBoxHeight,
              overflow: isGallery ? 'hidden' : 'visible',
              minHeight: isGallery ? 220 : 400,
              ...(isGallery ? {} : { minHeight: 400 }),
            }}
          >
            {content}
          </Box>
        </Box>

        {!isGallery && (
          <Text size="sm" c="gray.6" mt="md" ta="right">
            {chart.metadata?.source}
          </Text>
        )}

        {!isPdfMode && action !== 'toggle' && (
          <Group mt={isGallery ? 'xs' : 'md'}>
            {action === 'add' ? (
              <AddChart chart={chart} defId={defId} />
            ) : action === 'remove' ? (
              <RemoveChart chart={chart} />
            ) : null}
          </Group>
        )}
      </Card>
      <Modal
        opened={expanded}
        onClose={() => setExpanded(false)}
        size="100%"
        centered
        withCloseButton={false}
        overlayProps={{
          backgroundOpacity: 0.55,
          blur: 4,
        }}
      >
        <ActionIcon
          component={motion.button}
          pos="absolute"
          top={12}
          right={12}
          variant="transparent"
          color="grey"
          whileHover={{ scale: 1.15 }}
          whileTap={{ scale: 0.9 }}
          onClick={() => setExpanded(false)}
          style={{ zIndex: 1000 }}
        >
          <CornersInIcon size={50} weight="thin" color="grey" />
        </ActionIcon>

        <ChartCard
          chart={chart}
          ChartComponent={ChartComponent}
          TrendComponent={TrendComponent}
          matchedCategories={matchedCategories}
          action={action}
          defId={defId}
          isIncluded={isIncluded}
          onToggle={onToggle}
          view="report"
          border={false}
        />
      </Modal>
    </>
  );
};

import * as allCharts from './index';

interface ChartStackItemProps<TData extends DataRow> {
  chart: ChartItem<TData>;
  action?: 'add' | 'remove' | 'toggle';
  view?: 'gallery' | 'report';
  userInterests?: string[];
  defId?: string;
  isIncludedFn?: (defId: string) => boolean;
  onToggle?: (defId: string) => void;
  dragHandleProps?: ChartCardProps<TData>['dragHandleProps'];
  /** Data not fetched yet: show a skeleton rather than "no data". */
  loading?: boolean;
}

/**
 * Resolves a single ChartItem to its rendered form (ChartCard, note card, or
 * "no data" placeholder). Extracted from ChartStack's map so the
 * working-report page can render sortable chart cards one at a time (via
 * @dnd-kit) while sharing the exact same resolution logic.
 */
export const ChartStackItem = <TData extends DataRow>({
  chart,
  action = 'add',
  view,
  userInterests = [],
  defId,
  isIncludedFn,
  onToggle,
  dragHandleProps,
  loading = false,
}: ChartStackItemProps<TData>) => {
  const ChartComponent = allCharts[
    chart.subtype as keyof typeof allCharts
  ] as React.FC<{ chart: ChartItem<TData> }>;

  const TrendComponent = chart.trendChart
    ? (allCharts[chart.trendChart as keyof typeof allCharts] as React.FC<{
        chart: ChartItem<TData>;
      }>)
    : undefined;

  const matchedCategories =
    userInterests.length > 0 && chart.categories
      ? chart.categories.filter((cat) => userInterests.includes(cat))
      : [];

  const included = defId && isIncludedFn ? isIncludedFn(defId) : true;
  const handleToggle = defId && onToggle ? () => onToggle(defId) : undefined;

  if (chart.subtype === 'noteCard')
    return (
      <Card shadow="sm" padding="sm" radius="md" withBorder>
        <Text size="sm" c="dimmed">
          {chart.notes}
        </Text>
      </Card>
    );

  if (!ChartComponent) return null;
  if (loading)
    return (
      <Card shadow="sm" padding="sm" radius="md" withBorder>
        <Skeleton h={20} w="60%" mb="xs" />
        <Skeleton h={14} w="90%" mb={4} />
        <Skeleton h={14} w="80%" mb="md" />
        <Skeleton h={275} />
      </Card>
    );
  if (!chart.data || chart.data.length === 0)
    return (
      <Card shadow="sm" padding="lg" radius="md" withBorder>
        <Text>
          No data available from {`${chart.title}`}
          {chart.description ? ` for ${chart.description}` : ''}.
        </Text>
      </Card>
    );

  return (
    <ChartCard
      chart={chart}
      action={action}
      view={view}
      ChartComponent={ChartComponent}
      TrendComponent={TrendComponent}
      matchedCategories={matchedCategories}
      defId={defId}
      isIncluded={included}
      onToggle={handleToggle}
      dragHandleProps={dragHandleProps}
    />
  );
};

/**
 * Calls `onVisible` once, the first time the slot is within ~400px of the
 * viewport, so a chart can start fetching just before it scrolls in. The
 * wrapper is a grid so the card still stretches to its row's height.
 */
const LazySlot = ({
  onVisible,
  children,
}: {
  onVisible: () => void;
  children: React.ReactNode;
}) => {
  const { ref, entry } = useIntersection<HTMLDivElement>({
    rootMargin: '400px',
  });
  const seen = useRef(false);
  useEffect(() => {
    if (entry?.isIntersecting && !seen.current) {
      seen.current = true;
      onVisible();
    }
  }, [entry, onVisible]);
  return (
    <div ref={ref} style={{ display: 'grid' }}>
      {children}
    </div>
  );
};

interface ChartStackProps<TData extends DataRow> {
  charts: ChartItem<TData>[];
  action?: 'add' | 'remove' | 'toggle';
  userInterests?: string[];
  defIds?: (string | undefined)[];
  view?: 'gallery' | 'report';
  onToggle?: (defId: string) => void;
  isIncludedFn?: (defId: string) => boolean;
  /** Lazy loading ids per chart; falls back to `defIds` where undefined. */
  loadIds?: (string | undefined)[];
  /** Lazy loading: called once when a chart's card nears the viewport. */
  onVisible?: (defId: string) => void;
  /** Lazy loading: true while a chart's data hasn't arrived. */
  isLoading?: (defId: string) => boolean;
}

export const ChartStack = <TData extends DataRow>({
  charts,
  action = 'add',
  userInterests = [],
  defIds,
  view,
  onToggle,
  isIncludedFn,
  loadIds,
  onVisible,
  isLoading,
}: ChartStackProps<TData>) => {
  const isGallery = view === 'gallery';
  const Wrapper = isGallery ? SimpleGrid : Stack;
  const wrapperProps = isGallery
    ? { cols: { base: 1, sm: 2, lg: 2 }, spacing: 'md', verticalSpacing: 'md' }
    : {};

  return (
    <Box px="md" w="100%">
      <Wrapper {...wrapperProps} mt={5}>
        {charts.map((chart, i) => {
          const defId = defIds?.[i];
          const loadId = loadIds?.[i] ?? defId;
          const item = (
            <ChartStackItem
              key={defId ?? chart.id}
              chart={chart}
              action={action}
              view={view}
              userInterests={userInterests}
              defId={defId}
              isIncludedFn={isIncludedFn}
              onToggle={onToggle}
              loading={!!loadId && !!isLoading?.(loadId)}
            />
          );
          return loadId && onVisible ? (
            <LazySlot key={loadId} onVisible={() => onVisible(loadId)}>
              {item}
            </LazySlot>
          ) : (
            item
          );
        })}
      </Wrapper>
    </Box>
  );
};
