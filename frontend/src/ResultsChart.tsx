import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import { DataZoomComponent, GridComponent, TooltipComponent } from "echarts/components";
import ReactECharts from "echarts-for-react/lib/core";
import { CanvasRenderer } from "echarts/renderers";
import type { EChartsOption } from "echarts";

echarts.use([LineChart, DataZoomComponent, GridComponent, TooltipComponent, CanvasRenderer]);

export default function ResultsChart({ option }: { option: EChartsOption }) {
  return <ReactECharts option={option} style={{ height: 304, width: "100%" }} notMerge lazyUpdate />;
}
