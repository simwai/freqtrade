import * as echarts from 'echarts/core'
import { LineChart, BarChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, GridComponent, DatasetComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { LineSeriesOption, BarSeriesOption } from 'echarts/charts'
import type { TitleComponentOption, TooltipComponentOption, GridComponentOption, DatasetComponentOption } from 'echarts/components'
import type { ComposeOption } from 'echarts/core'
export type ECOption = ComposeOption<LineSeriesOption | BarSeriesOption | TitleComponentOption | TooltipComponentOption | GridComponentOption | DatasetComponentOption>
echarts.use([LineChart, BarChart, TitleComponent, TooltipComponent, GridComponent, DatasetComponent, CanvasRenderer])
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
