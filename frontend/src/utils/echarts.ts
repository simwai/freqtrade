import * as echarts from 'echarts/core'
import { LineChart, BarChart, BoxplotChart, ScatterChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, GridComponent, DatasetComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { LineSeriesOption, BarSeriesOption, BoxplotSeriesOption, ScatterSeriesOption } from 'echarts/charts'
import type { TitleComponentOption, TooltipComponentOption, GridComponentOption, DatasetComponentOption, LegendComponentOption } from 'echarts/components'
import type { ComposeOption } from 'echarts/core'
export type ECOption = ComposeOption<LineSeriesOption | BarSeriesOption | BoxplotSeriesOption | ScatterSeriesOption | TitleComponentOption | TooltipComponentOption | GridComponentOption | DatasetComponentOption | LegendComponentOption>
echarts.use([LineChart, BarChart, BoxplotChart, ScatterChart, TitleComponent, TooltipComponent, GridComponent, DatasetComponent, LegendComponent, CanvasRenderer])
echarts.registerTheme('lab', {
  backgroundColor: 'transparent',
  tooltip: {
    backgroundColor: '#1b1628',
    borderColor: '#2f2745',
    borderWidth: 1,
    textStyle: { color: '#e9e4f5', fontSize: 12 }
  },
})
export default echarts
export type ECScatterOption = ComposeOption<ScatterSeriesOption | TooltipComponentOption | GridComponentOption>
import { CandlestickChart, CustomChart } from 'echarts/charts'
import type { CandlestickSeriesOption, CustomSeriesOption } from 'echarts/charts'
import { DataZoomComponent } from 'echarts/components'
import type { DataZoomComponentOption } from 'echarts/components'
echarts.use([CandlestickChart, CustomChart, DataZoomComponent])
export type ECOption2 = ComposeOption<ScatterSeriesOption | CandlestickSeriesOption | CustomSeriesOption | LineSeriesOption | BarSeriesOption | TooltipComponentOption | GridComponentOption | DataZoomComponentOption>
