<template>
  <div class="scc-graph-container" ref="container"></div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import * as d3 from 'd3'
import type { SccNode, SccEdge } from '../api/schemas'

interface Props {
  nodes: SccNode[]
  edges: SccEdge[]
}

const props = defineProps<Props>()

const container = ref<HTMLElement | null>(null)
let simulation: any = null
let svg: any = null

function renderGraph() {
  if (!container.value || !props.nodes.length) return

  const width = container.value.clientWidth || 800
  const height = 500

  // Clear previous
  d3.select(container.value).selectAll('*').remove()

  svg = d3.select(container.value)
    .append('svg')
    .attr('width', '100%')
    .attr('height', '100%')
    .attr('viewBox', `0 0 ${width} ${height}`)
    .style('font-family', 'inherit')

  // Arrow markers
  svg.append('defs').append('marker')
    .attr('id', 'arrowhead')
    .attr('viewBox', '0 -5 10 10')
    .attr('refX', 20)
    .attr('refY', 0)
    .attr('orient', 'auto')
    .attr('markerWidth', 6)
    .attr('markerHeight', 6)
    .append('path')
    .attr('d', 'M0,-5L10,0L0,5')
    .attr('fill', '#a89fc4')

  // Links
  const link = svg.append('g')
    .attr('class', 'links')
    .selectAll('line')
    .data(props.edges)
    .join('line')
    .attr('stroke', '#a89fc4')
    .attr('stroke-opacity', 0.6)
    .attr('stroke-width', (d: any) => Math.max(1, Math.min(4, d.weight * 10)))
    .attr('marker-end', 'url(#arrowhead)')

  // Nodes
  const node = svg.append('g')
    .attr('class', 'nodes')
    .selectAll('g')
    .data(props.nodes)
    .join('g')
    .call(drag(simulation))

  node.append('circle')
    .attr('r', 20)
    .attr('fill', '#a78bfa')
    .attr('stroke', '#fff')
    .attr('stroke-width', 2)

  node.append('text')
    .attr('dy', 4)
    .attr('text-anchor', 'middle')
    .attr('font-size', 10)
    .attr('fill', '#fff')
    .attr('font-weight', 600)
    .text((d: any) => d.label.length > 12 ? d.label.slice(0, 12) + '…' : d.label)

  // Tooltip
  node.append('title')
    .text((d: any) => `${d.label}\nStartup candles: ${d.startup_candles}\nIndicators: ${d.indicators.join(', ')}`)

  simulation = d3.forceSimulation(props.nodes as any)
    .force('link', d3.forceLink(props.edges).id((d: any) => d.id).distance(80).strength(0.5))
    .force('charge', d3.forceManyBody().strength(-300))
    .force('center', d3.forceCenter(width / 2, height / 2))
    .force('collision', d3.forceCollide().radius(30))
    .on('tick', ticked)

  function ticked() {
    link
      .attr('x1', (d: any) => d.source.x)
      .attr('y1', (d: any) => d.source.y)
      .attr('x2', (d: any) => d.target.x)
      .attr('y2', (d: any) => d.target.y)

    node
      .attr('transform', (d: any) => `translate(${d.x},${d.y})`)
  }

  function drag(sim: any) {
    return d3.drag()
      .on('start', (event: any, d: any) => {
        if (!event.active) sim.alphaTarget(0.3).restart()
        d.fx = d.x
        d.fy = d.y
      })
      .on('drag', (event: any, d: any) => {
        d.fx = event.x
        d.fy = event.y
      })
      .on('end', (event: any, d: any) => {
        if (!event.active) sim.alphaTarget(0)
        d.fx = null
        d.fy = null
      })
  }
}

onMounted(() => {
  renderGraph()
})

watch(() => [props.nodes.length, props.edges.length], () => {
  renderGraph()
}, { deep: true })

onUnmounted(() => {
  if (simulation) simulation.stop()
})
</script>

<style scoped>
.scc-graph-container {
  width: 100%;
  height: 500px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
}
</style>
