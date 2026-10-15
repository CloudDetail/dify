/** @jest-environment node */
import { topologyUnavailableReason, usePrepareTopologyData } from './hook'

describe('资源告警无服务拓扑时的展示', () => {
  const reason = '未关联唯一服务，跳过服务拓扑查询'
  it('兼容现场 unresolved_instance 响应，保留原因且不生成假节点', () => {
    const payload = { type: 'topology', display: true, data: {}, status: 'unresolved_instance', reason }
    expect(usePrepareTopologyData(payload.data)).toEqual({ nodes: [], edges: [] })
    expect(topologyUnavailableReason(payload, '暂无拓扑')).toBe(reason)
  })
  it.each([null, undefined, {}, { current: null }, { current: {} }, { current: { service: '' } }])('空数据不抛异常: %j', (data) => {
    expect(usePrepareTopologyData(data)).toEqual({ nodes: [], edges: [] })
    expect(topologyUnavailableReason({ data }, '暂无拓扑')).toBe('暂无拓扑')
  })
  it('接口错误保持错误原因，不伪装为空数据', () => {
    expect(topologyUnavailableReason({ data: {}, error: 'COS query failed' }, '暂无拓扑')).toBe('COS query failed')
  })
  it('有真实服务时保留原拓扑节点和父边', () => {
    const data = { current: { service: 'order', endpoint: '/order' }, parents: [{ service: 'gateway', endpoint: '/' }] }
    const graph = usePrepareTopologyData(data)
    expect(graph.nodes.map(n => n.data.service)).toEqual(['order', 'gateway'])
    expect(graph.edges).toHaveLength(1)
    expect(topologyUnavailableReason({ data }, '暂无拓扑')).toBeNull()
  })
})
