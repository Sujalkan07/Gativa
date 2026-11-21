import React, { useRef, useEffect, useState, useCallback, useMemo } from 'react'
import type {
  RoadNetworkGeometryResponse,
  NetworkEdgeDetail,
  NetworkJunctionDetail,
  VehiclePosition,
  TrafficLightState,
} from '../../types/api'

interface RoadNetworkRendererProps {
  networkGeometry: RoadNetworkGeometryResponse | null
  vehicles: VehiclePosition[]
  trafficLights?: TrafficLightState[]
  selectedEdgeId?: string | null
  selectedJunctionId?: string | null
  onSelectEdge?: (edge: NetworkEdgeDetail | null) => void
  onSelectJunction?: (junction: NetworkJunctionDetail | null) => void
  onSelectVehicle?: (vehicle: VehiclePosition | null) => void
  focusedVehicleId?: string | null
  height?: number | string
  isSimulating?: boolean
}

export default function RoadNetworkRenderer({
  networkGeometry,
  vehicles,
  trafficLights = [],
  selectedEdgeId,
  selectedJunctionId,
  onSelectEdge,
  onSelectJunction,
  focusedVehicleId,
  height = 560,
}: RoadNetworkRendererProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)

  // Viewport transformation: scale (pixels per meter) and offset in screen coordinates
  const [viewport, setViewport] = useState<{ scale: number; offsetX: number; offsetY: number }>({
    scale: 1.0,
    offsetX: 0,
    offsetY: 0,
  })
  const isDraggingRef = useRef(false)
  const dragStartRef = useRef<{ x: number; y: number; startOffsetX: number; startOffsetY: number }>({
    x: 0,
    y: 0,
    startOffsetX: 0,
    startOffsetY: 0,
  })

  const [hoveredInfo, setHoveredInfo] = useState<{
    x: number
    y: number
    title: string
    subtitle: string
    details: string[]
  } | null>(null)

  // Compute projection parameters based on network bounds
  const proj = useMemo(() => {
    if (!networkGeometry || !networkGeometry.bounds) {
      return null
    }
    const [minLng, minLat, maxLng, maxLat] = networkGeometry.bounds
    const midLat = (minLat + maxLat) / 2
    const latRad = (midLat * Math.PI) / 180
    const metersPerLng = 111320 * Math.cos(latRad)
    const metersPerLat = 111320

    const widthMeters = Math.max(10, (maxLng - minLng) * metersPerLng)
    const heightMeters = Math.max(10, (maxLat - minLat) * metersPerLat)

    return {
      minLng,
      minLat,
      metersPerLng,
      metersPerLat,
      widthMeters,
      heightMeters,
    }
  }, [networkGeometry])

  // Convert Geo [lng, lat] to local meter coordinates [x_m, y_m]
  const geoToMeters = useCallback(
    (lng: number, lat: number): [number, number] => {
      if (!proj) return [0, 0]
      const xm = (lng - proj.minLng) * proj.metersPerLng
      const ym = (lat - proj.minLat) * proj.metersPerLat
      return [xm, ym]
    },
    [proj]
  )

  // Convert local meter coordinates to screen coordinates
  const metersToScreen = useCallback(
    (xm: number, ym: number, canvasHeight: number, scale: number, offsetX: number, offsetY: number): [number, number] => {
      const sx = offsetX + xm * scale
      const sy = canvasHeight - (offsetY + ym * scale)
      return [sx, sy]
    },
    []
  )

  // Convert screen coordinates to local meter coordinates
  const screenToMeters = useCallback(
    (sx: number, sy: number, canvasHeight: number, scale: number, offsetX: number, offsetY: number): [number, number] => {
      const xm = (sx - offsetX) / scale
      const ym = (canvasHeight - sy - offsetY) / scale
      return [xm, ym]
    },
    []
  )

  // Auto-fit network to canvas viewport
  const fitNetwork = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas || !proj) return
    const padding = 60
    const availW = canvas.width - padding * 2
    const availH = canvas.height - padding * 2

    const scaleX = availW / proj.widthMeters
    const scaleY = availH / proj.heightMeters
    const newScale = Math.max(0.05, Math.min(scaleX, scaleY))

    const netCenterXM = proj.widthMeters / 2
    const netCenterYM = proj.heightMeters / 2

    const newOffsetX = canvas.width / 2 - netCenterXM * newScale
    const newOffsetY = canvas.height / 2 - netCenterYM * newScale

    setViewport({
      scale: newScale,
      offsetX: newOffsetX,
      offsetY: newOffsetY,
    })
  }, [proj])

  // Fit study area (core polygon) to canvas viewport with comfortable framing
  const fitSelectedArea = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas || !proj) return

    if (!networkGeometry?.polygon_coords || networkGeometry.polygon_coords.length < 3) {
      fitNetwork()
      return
    }

    const polyMeters = networkGeometry.polygon_coords.map((c) => geoToMeters(c[0], c[1]))
    const minXM = Math.min(...polyMeters.map((p) => p[0]))
    const maxXM = Math.max(...polyMeters.map((p) => p[0]))
    const minYM = Math.min(...polyMeters.map((p) => p[1]))
    const maxYM = Math.max(...polyMeters.map((p) => p[1]))

    const polyW = Math.max(15, maxXM - minXM)
    const polyH = Math.max(15, maxYM - minYM)
    const padding = 70
    const availW = canvas.width - padding * 2
    const availH = canvas.height - padding * 2

    const scaleX = availW / polyW
    const scaleY = availH / polyH
    const newScale = Math.max(0.05, Math.min(25.0, Math.min(scaleX, scaleY)))

    const centerXM = (minXM + maxXM) / 2
    const centerYM = (minYM + maxYM) / 2

    const newOffsetX = canvas.width / 2 - centerXM * newScale
    const newOffsetY = canvas.height / 2 - centerYM * newScale

    setViewport({
      scale: newScale,
      offsetX: newOffsetX,
      offsetY: newOffsetY,
    })
  }, [proj, networkGeometry, geoToMeters, fitNetwork])

  // Initial camera: Focus cleanly on the selected study area by default
  useEffect(() => {
    if (proj) {
      if (networkGeometry?.polygon_coords && networkGeometry.polygon_coords.length >= 3) {
        fitSelectedArea()
      } else {
        fitNetwork()
      }
    }
  }, [proj, networkGeometry?.sim_id, networkGeometry?.polygon_coords, fitSelectedArea, fitNetwork])

  // Focus on selected edge when chosen by user
  useEffect(() => {
    if (!selectedEdgeId || !canvasRef.current || !proj || !networkGeometry) return
    const edge = networkGeometry.edges.find((e) => e.id === selectedEdgeId || e.edge_id === selectedEdgeId)
    if (!edge || !edge.shape || edge.shape.length < 2) return

    const midIdx = Math.floor(edge.shape.length / 2)
    const [midLng, midLat] = edge.shape[midIdx]
    const [exm, eym] = geoToMeters(midLng, midLat)
    const canvas = canvasRef.current

    setViewport((prev) => {
      const targetScale = Math.max(prev.scale, 2.2)
      return {
        scale: targetScale,
        offsetX: canvas.width / 2 - exm * targetScale,
        offsetY: canvas.height / 2 - eym * targetScale,
      }
    })
  }, [selectedEdgeId, networkGeometry, geoToMeters, proj])

  // Focus on selected junction when chosen by user
  useEffect(() => {
    if (!selectedJunctionId || !canvasRef.current || !proj || !networkGeometry) return
    const junction = networkGeometry.junctions.find((j) => j.id === selectedJunctionId || j.junction_id === selectedJunctionId)
    if (!junction) return

    const [jxm, jym] = geoToMeters(junction.x, junction.y)
    const canvas = canvasRef.current

    setViewport((prev) => {
      const targetScale = Math.max(prev.scale, 2.8)
      return {
        scale: targetScale,
        offsetX: canvas.width / 2 - jxm * targetScale,
        offsetY: canvas.height / 2 - jym * targetScale,
      }
    })
  }, [selectedJunctionId, networkGeometry, geoToMeters, proj])

  // Focus on selected vehicle if provided
  useEffect(() => {
    if (!focusedVehicleId || !canvasRef.current || !proj) return
    const veh = vehicles.find((v) => v.id === focusedVehicleId)
    if (!veh) return

    const [vxm, vym] = geoToMeters(veh.lng, veh.lat)
    const canvas = canvasRef.current
    const targetScale = Math.max(viewport.scale, 2.5) // Zoom in on vehicle
    const targetOffsetX = canvas.width / 2 - vxm * targetScale
    const targetOffsetY = canvas.height / 2 - vym * targetScale

    setViewport({
      scale: targetScale,
      offsetX: targetOffsetX,
      offsetY: targetOffsetY,
    })
  }, [focusedVehicleId, vehicles, geoToMeters, proj, viewport.scale])

  // Resize canvas when container size changes
  useEffect(() => {
    const canvas = canvasRef.current
    const container = containerRef.current
    if (!canvas || !container) return

    const resizeObserver = new ResizeObserver(() => {
      const rect = container.getBoundingClientRect()
      const dpr = window.devicePixelRatio || 1
      canvas.width = rect.width * dpr
      canvas.height = rect.height * dpr
      canvas.style.width = `${rect.width}px`
      canvas.style.height = `${rect.height}px`
    })

    resizeObserver.observe(container)
    return () => resizeObserver.disconnect()
  }, [])

  // Mouse interaction handlers for Pan and Zoom
  const handleMouseDown = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (e.button !== 0) return
    isDraggingRef.current = true
    dragStartRef.current = {
      x: e.clientX,
      y: e.clientY,
      startOffsetX: viewport.offsetX,
      startOffsetY: viewport.offsetY,
    }
  }

  const handleMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current
    if (!canvas) return
    const rect = canvas.getBoundingClientRect()
    const dpr = window.devicePixelRatio || 1
    const mouseX = (e.clientX - rect.left) * dpr
    const mouseY = (e.clientY - rect.top) * dpr

    if (isDraggingRef.current) {
      const dx = (e.clientX - dragStartRef.current.x) * dpr
      const dy = (e.clientY - dragStartRef.current.y) * dpr
      setViewport((prev) => ({
        ...prev,
        offsetX: dragStartRef.current.startOffsetX + dx,
        offsetY: dragStartRef.current.startOffsetY - dy,
      }))
      return
    }

    // Hit test roads and junctions for hover tooltip
    if (!networkGeometry || !proj) return
    const [xm, ym] = screenToMeters(mouseX, mouseY, canvas.height, viewport.scale, viewport.offsetX, viewport.offsetY)

    // Check junctions first (smaller targets)
    const junctionHitRadiusMeters = Math.max(12, 16 / viewport.scale)
    const hitJunction = networkGeometry.junctions.find((j) => {
      const [jxm, jym] = geoToMeters(j.x, j.y)
      const dist = Math.hypot(jxm - xm, jym - ym)
      return dist <= junctionHitRadiusMeters
    })

    if (hitJunction) {
      setHoveredInfo({
        x: e.clientX - rect.left,
        y: e.clientY - rect.top,
        title: `Junction ${hitJunction.id}`,
        subtitle: hitJunction.has_traffic_light ? 'Signalized Intersection' : 'Priority Junction',
        details: [
          `Type: ${hitJunction.type}`,
          `Incoming roads: ${hitJunction.incoming_edges.length}`,
          `Outgoing roads: ${hitJunction.outgoing_edges.length}`,
        ],
      })
      canvas.style.cursor = 'pointer'
      return
    }

    // Check road edges
    const edgeHitRadiusMeters = Math.max(8, 12 / viewport.scale)
    let hitEdge: NetworkEdgeDetail | null = null

    for (const edge of networkGeometry.edges) {
      const pts = edge.shape
      if (pts.length < 2) continue
      for (let i = 0; i < pts.length - 1; i++) {
        const [x1, y1] = geoToMeters(pts[i][0], pts[i][1])
        const [x2, y2] = geoToMeters(pts[i + 1][0], pts[i + 1][1])
        const dist = distToSegment(xm, ym, x1, y1, x2, y2)
        if (dist <= edgeHitRadiusMeters) {
          hitEdge = edge
          break
        }
      }
      if (hitEdge) break
    }

    if (hitEdge) {
      const edgeId = hitEdge.edge_id || hitEdge.id
      const activeOnEdge = vehicles.filter((v) => v.lane_id?.startsWith(edgeId)).length
      setHoveredInfo({
        x: e.clientX - rect.left,
        y: e.clientY - rect.top,
        title: hitEdge.name,
        subtitle: `${hitEdge.road_type.toUpperCase()} • ${hitEdge.num_lanes} Lanes`,
        details: [
          `ID: ${edgeId}`,
          `Speed Limit: ${hitEdge.speed_kmh} km/h`,
          `Length: ${hitEdge.length_m} m`,
          `One-way: ${hitEdge.is_oneway ? 'Yes' : 'No'}`,
          `Active Vehicles: ${activeOnEdge}`,
          hitEdge.is_buffer ? 'Zone: External Buffer' : 'Zone: Interior Study Area',
        ],
      })
      canvas.style.cursor = 'pointer'
      return
    }

    setHoveredInfo(null)
    canvas.style.cursor = 'default'
  }

  const handleMouseUp = () => {
    isDraggingRef.current = false
  }

  const handleWheel = (e: React.WheelEvent<HTMLCanvasElement>) => {
    e.preventDefault()
    const canvas = canvasRef.current
    if (!canvas) return
    const rect = canvas.getBoundingClientRect()
    const dpr = window.devicePixelRatio || 1
    const mouseX = (e.clientX - rect.left) * dpr
    const mouseY = (e.clientY - rect.top) * dpr

    const zoomFactor = e.deltaY < 0 ? 1.15 : 0.87
    const newScale = Math.max(0.01, Math.min(20.0, viewport.scale * zoomFactor))

    // Zoom centered on cursor
    const [xm, ym] = screenToMeters(mouseX, mouseY, canvas.height, viewport.scale, viewport.offsetX, viewport.offsetY)
    const newOffsetX = mouseX - xm * newScale
    const newOffsetY = canvas.height - mouseY - ym * newScale

    setViewport({
      scale: newScale,
      offsetX: newOffsetX,
      offsetY: newOffsetY,
    })
  }

  const handleClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current
    if (!canvas || !networkGeometry || !proj) return
    const rect = canvas.getBoundingClientRect()
    const dpr = window.devicePixelRatio || 1
    const mouseX = (e.clientX - rect.left) * dpr
    const mouseY = (e.clientY - rect.top) * dpr

    const [xm, ym] = screenToMeters(mouseX, mouseY, canvas.height, viewport.scale, viewport.offsetX, viewport.offsetY)

    // Check junction selection
    const junctionHitRadiusMeters = Math.max(14, 18 / viewport.scale)
    const hitJunction = networkGeometry.junctions.find((j) => {
      const [jxm, jym] = geoToMeters(j.x, j.y)
      return Math.hypot(jxm - xm, jym - ym) <= junctionHitRadiusMeters
    })

    if (hitJunction && onSelectJunction) {
      onSelectJunction(hitJunction)
      if (onSelectEdge) onSelectEdge(null)
      return
    }

    // Check edge selection
    const edgeHitRadiusMeters = Math.max(8, 14 / viewport.scale)
    let hitEdge: NetworkEdgeDetail | null = null
    for (const edge of networkGeometry.edges) {
      const pts = edge.shape
      if (pts.length < 2) continue
      for (let i = 0; i < pts.length - 1; i++) {
        const [x1, y1] = geoToMeters(pts[i][0], pts[i][1])
        const [x2, y2] = geoToMeters(pts[i + 1][0], pts[i + 1][1])
        if (distToSegment(xm, ym, x1, y1, x2, y2) <= edgeHitRadiusMeters) {
          hitEdge = edge
          break
        }
      }
      if (hitEdge) break
    }

    if (hitEdge && onSelectEdge) {
      onSelectEdge(hitEdge)
      if (onSelectJunction) onSelectJunction(null)
      return
    }

    // Clicked empty space: clear selection
    if (onSelectEdge) onSelectEdge(null)
    if (onSelectJunction) onSelectJunction(null)
  }

  // ─── Main Canvas Render Loop ───────────────────────────────────────────────
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || !proj || !networkGeometry) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const { width: w, height: h } = canvas
    const { scale, offsetX, offsetY } = viewport

    // Clear background to dark SUMO canvas color
    ctx.fillStyle = '#0b1120' // Deep slate navy
    ctx.fillRect(0, 0, w, h)

    // 1. Draw Subtle Grid Pattern in Meters
    const gridSpacingMeters = scale > 3 ? 20 : scale > 0.8 ? 100 : 500
    const [minScreenXM, minScreenYM] = screenToMeters(0, h, h, scale, offsetX, offsetY)
    const [maxScreenXM, maxScreenYM] = screenToMeters(w, 0, h, scale, offsetX, offsetY)

    ctx.strokeStyle = 'rgba(255, 255, 255, 0.03)'
    ctx.lineWidth = 1
    const startX = Math.floor(minScreenXM / gridSpacingMeters) * gridSpacingMeters
    for (let gx = startX; gx <= maxScreenXM; gx += gridSpacingMeters) {
      const [sx] = metersToScreen(gx, 0, h, scale, offsetX, offsetY)
      ctx.beginPath()
      ctx.moveTo(sx, 0)
      ctx.lineTo(sx, h)
      ctx.stroke()
    }
    const startY = Math.floor(minScreenYM / gridSpacingMeters) * gridSpacingMeters
    for (let gy = startY; gy <= maxScreenYM; gy += gridSpacingMeters) {
      const [, sy] = metersToScreen(0, gy, h, scale, offsetX, offsetY)
      ctx.beginPath()
      ctx.moveTo(0, sy)
      ctx.lineTo(w, sy)
      ctx.stroke()
    }

    // 2. Draw Selected Analysis Polygon Boundary
    if (networkGeometry.polygon_coords && networkGeometry.polygon_coords.length >= 3) {
      ctx.beginPath()
      networkGeometry.polygon_coords.forEach((coord, i) => {
        const [xm, ym] = geoToMeters(coord[0], coord[1])
        const [sx, sy] = metersToScreen(xm, ym, h, scale, offsetX, offsetY)
        if (i === 0) ctx.moveTo(sx, sy)
        else ctx.lineTo(sx, sy)
      })
      ctx.closePath()
      ctx.fillStyle = 'rgba(56, 189, 248, 0.04)'
      ctx.fill()
      ctx.strokeStyle = 'rgba(56, 189, 248, 0.5)'
      ctx.lineWidth = Math.max(1.5, 2)
      ctx.setLineDash([8, 6])
      ctx.stroke()
      ctx.setLineDash([])
    }

    // 3. Draw Road Network (Asphalt Surfaces and Lane Markings)
    // First pass: Asphalt base for all edges
    networkGeometry.edges.forEach((edge) => {
      const isBuffer = edge.is_buffer
      const isSelected = selectedEdgeId === edge.id || selectedEdgeId === edge.edge_id
      const numLanes = edge.num_lanes || 1
      const roadWidthM = Math.max(3.2, numLanes * 3.5)
      const roadWidthPx = Math.max(2, roadWidthM * scale)

      const pts = edge.shape
      if (pts.length < 2) return

      ctx.beginPath()
      pts.forEach((pt, i) => {
        const [xm, ym] = geoToMeters(pt[0], pt[1])
        const [sx, sy] = metersToScreen(xm, ym, h, scale, offsetX, offsetY)
        if (i === 0) ctx.moveTo(sx, sy)
        else ctx.lineTo(sx, sy)
      })

      // Outer border / asphalt
      ctx.lineCap = 'round'
      ctx.lineJoin = 'round'
      ctx.lineWidth = roadWidthPx
      ctx.strokeStyle = isBuffer
        ? 'rgba(30, 41, 59, 0.6)'
        : isSelected
        ? '#0369a1'
        : '#1e293b'
      ctx.stroke()

      // Selection glow
      if (isSelected) {
        ctx.strokeStyle = 'rgba(56, 189, 248, 0.8)'
        ctx.lineWidth = roadWidthPx + 4
        ctx.stroke()
        ctx.strokeStyle = '#0284c7'
        ctx.lineWidth = roadWidthPx
        ctx.stroke()
      }
    })

    // Second pass: Individual Lanes and Divider Markings
    networkGeometry.edges.forEach((edge) => {
      const isBuffer = edge.is_buffer
      const numLanes = edge.num_lanes || 1
      const isOneway = edge.is_oneway

      if (edge.lanes && edge.lanes.length > 0) {
        edge.lanes.forEach((lane) => {
          const lShape = lane.shape
          if (lShape.length < 2) return

          // Center trajectory of lane
          ctx.beginPath()
          lShape.forEach((lpt, idx) => {
            const [lxm, lym] = geoToMeters(lpt[0], lpt[1])
            const [lsx, lsy] = metersToScreen(lxm, lym, h, scale, offsetX, offsetY)
            if (idx === 0) ctx.moveTo(lsx, lsy)
            else ctx.lineTo(lsx, lsy)
          })

          const laneWidthPx = Math.max(1.5, lane.width_m * scale)
          ctx.lineWidth = Math.max(1, laneWidthPx * 0.95)
          ctx.strokeStyle = isBuffer ? 'rgba(51, 65, 85, 0.5)' : '#334155'
          ctx.stroke()
        })
      }

      // Draw Centerline / Lane Divider Markings if scale is sufficient
      if (scale > 0.4 && edge.shape.length >= 2) {
        ctx.beginPath()
        edge.shape.forEach((pt, i) => {
          const [xm, ym] = geoToMeters(pt[0], pt[1])
          const [sx, sy] = metersToScreen(xm, ym, h, scale, offsetX, offsetY)
          if (i === 0) ctx.moveTo(sx, sy)
          else ctx.lineTo(sx, sy)
        })

        if (!isOneway && numLanes >= 2) {
          // Double yellow line for two-way roads
          ctx.strokeStyle = isBuffer ? 'rgba(234, 179, 8, 0.35)' : '#eab308'
          ctx.lineWidth = Math.max(1, 1.5 * scale)
          ctx.setLineDash([])
          ctx.stroke()
        } else if (numLanes > 1) {
          // Dashed white divider for one-way multi-lane roads
          ctx.strokeStyle = isBuffer ? 'rgba(203, 213, 225, 0.25)' : 'rgba(203, 213, 225, 0.65)'
          ctx.lineWidth = Math.max(1, 1.2 * scale)
          ctx.setLineDash([Math.max(3, 4 * scale), Math.max(3, 5 * scale)])
          ctx.stroke()
          ctx.setLineDash([])
        }
      }
    })

    // 4. Draw Junctions (Intersection Pavements and Shape Polygons)
    networkGeometry.junctions.forEach((junction) => {
      const isSelected = selectedJunctionId === junction.id || selectedJunctionId === junction.junction_id
      const [jxm, jym] = geoToMeters(junction.x, junction.y)
      const [jsx, jsy] = metersToScreen(jxm, jym, h, scale, offsetX, offsetY)

      // Draw junction polygon if available
      if (junction.shape && junction.shape.length >= 3) {
        ctx.beginPath()
        junction.shape.forEach((pt, i) => {
          const [pxm, pym] = geoToMeters(pt[0], pt[1])
          const [psx, psy] = metersToScreen(pxm, pym, h, scale, offsetX, offsetY)
          if (i === 0) ctx.moveTo(psx, psy)
          else ctx.lineTo(psx, psy)
        })
        ctx.closePath()
        ctx.fillStyle = isSelected ? '#3b0764' : '#1e293b'
        ctx.fill()
        ctx.strokeStyle = isSelected ? '#c084fc' : '#475569'
        ctx.lineWidth = isSelected ? 3 : 1
        ctx.stroke()
      } else {
        // Fallback circle
        const rad = Math.max(4, 6 * scale)
        ctx.beginPath()
        ctx.arc(jsx, jsy, rad, 0, Math.PI * 2)
        ctx.fillStyle = isSelected ? '#a855f7' : '#334155'
        ctx.fill()
        ctx.strokeStyle = isSelected ? '#f3e8ff' : '#64748b'
        ctx.lineWidth = isSelected ? 2.5 : 1
        ctx.stroke()
      }

      // Draw Traffic Light Aspect if signalized
      if (junction.has_traffic_light) {
        // Find matching live signal
        const liveSig = trafficLights.find(
          (tl) => tl.id === junction.id || junction.id === junction.tl_id || tl.controlled_junctions?.includes(junction.id)
        )
        const stateColor = liveSig
          ? liveSig.state.toLowerCase().includes('y')
            ? '#eab308' // Yellow
            : liveSig.is_green || liveSig.state.toLowerCase().includes('g')
            ? '#22c55e' // Green
            : '#ef4444' // Red
          : '#22c55e'

        const sigRad = Math.max(5, 7 * scale)
        // Glow pulse
        ctx.beginPath()
        ctx.arc(jsx, jsy, sigRad + 4, 0, Math.PI * 2)
        ctx.fillStyle = stateColor === '#22c55e' ? 'rgba(34, 197, 94, 0.25)' : stateColor === '#ef4444' ? 'rgba(239, 68, 68, 0.25)' : 'rgba(234, 179, 8, 0.25)'
        ctx.fill()

        // Core light
        ctx.beginPath()
        ctx.arc(jsx, jsy, sigRad, 0, Math.PI * 2)
        ctx.fillStyle = stateColor
        ctx.fill()
        ctx.strokeStyle = '#ffffff'
        ctx.lineWidth = 1.5
        ctx.stroke()
      }
    })

    // 5. Draw Top-Down Vehicle Sprites
    vehicles.forEach((veh) => {
      const [vxm, vym] = geoToMeters(veh.lng, veh.lat)
      const [vsx, vsy] = metersToScreen(vxm, vym, h, scale, offsetX, offsetY)

      // Cull vehicles outside screen
      if (vsx < -30 || vsx > w + 30 || vsy < -30 || vsy > h + 30) return

      const isFocused = veh.id === focusedVehicleId
      const angleRad = ((veh.angle || 0) * Math.PI) / 180

      // Physical dimensions based on vehicle type
      let lenM = 4.5
      let widM = 2.0
      let bodyColor = '#3b82f6' // passenger blue

      if (veh.type === 'bus') {
        lenM = 11.5
        widM = 2.6
        bodyColor = '#f59e0b' // bus amber
      } else if (veh.type === 'delivery') {
        lenM = 7.0
        widM = 2.2
        bodyColor = '#94a3b8' // delivery slate/silver
      } else if (veh.type === 'motorcycle') {
        lenM = 2.2
        widM = 1.0
        bodyColor = '#ef4444' // motorcycle red
      }

      // Clamped pixel dimensions
      const lenPx = Math.max(6, lenM * scale)
      const widPx = Math.max(3, widM * scale)

      ctx.save()
      ctx.translate(vsx, vsy)
      ctx.rotate(angleRad)

      // Target ring if focused
      if (isFocused) {
        ctx.beginPath()
        ctx.arc(0, 0, Math.max(14, lenPx * 1.4), 0, Math.PI * 2)
        ctx.strokeStyle = '#38bdf8'
        ctx.lineWidth = 2
        ctx.setLineDash([4, 4])
        ctx.stroke()
        ctx.setLineDash([])
      }

      // Headlight beams if moving
      if (veh.speed_kmh > 5.0 && scale > 0.6) {
        ctx.beginPath()
        ctx.moveTo(-widPx * 0.35, -lenPx * 0.5)
        ctx.lineTo(-widPx * 0.7, -lenPx * 0.5 - 12 * scale)
        ctx.lineTo(-widPx * 0.1, -lenPx * 0.5 - 14 * scale)
        ctx.closePath()
        ctx.fillStyle = 'rgba(254, 240, 138, 0.18)'
        ctx.fill()

        ctx.beginPath()
        ctx.moveTo(widPx * 0.35, -lenPx * 0.5)
        ctx.lineTo(widPx * 0.7, -lenPx * 0.5 - 12 * scale)
        ctx.lineTo(widPx * 0.1, -lenPx * 0.5 - 14 * scale)
        ctx.closePath()
        ctx.fillStyle = 'rgba(254, 240, 138, 0.18)'
        ctx.fill()
      }

      // Vehicle Chassis / Body
      ctx.fillStyle = bodyColor
      ctx.strokeStyle = '#0f172a'
      ctx.lineWidth = 1

      // Draw rounded rectangle for car body
      const halfW = widPx / 2
      const halfL = lenPx / 2
      const radius = Math.min(3, halfW * 0.5)

      ctx.beginPath()
      ctx.roundRect(-halfW, -halfL, widPx, lenPx, radius)
      ctx.fill()
      ctx.stroke()

      // Windshield & Roof details for larger scale
      if (lenPx >= 12) {
        // Front Windshield
        ctx.fillStyle = '#0f172a'
        ctx.beginPath()
        ctx.roundRect(-halfW * 0.75, -halfL * 0.45, widPx * 0.75, lenPx * 0.22, 1)
        ctx.fill()

        // Rear Windshield
        ctx.beginPath()
        ctx.roundRect(-halfW * 0.75, halfL * 0.22, widPx * 0.75, lenPx * 0.18, 1)
        ctx.fill()

        // Brake lights if stopped
        if (veh.waiting_time_s > 0) {
          ctx.fillStyle = '#ef4444'
          ctx.fillRect(-halfW * 0.85, halfL - 1.5, widPx * 0.3, 2)
          ctx.fillRect(halfW * 0.55, halfL - 1.5, widPx * 0.3, 2)
        }
      }

      ctx.restore()
    })
  }, [
    networkGeometry,
    vehicles,
    trafficLights,
    viewport,
    proj,
    geoToMeters,
    metersToScreen,
    screenToMeters,
    selectedEdgeId,
    selectedJunctionId,
    focusedVehicleId,
  ])

  return (
    <div ref={containerRef} className="relative w-full overflow-hidden select-none" style={{ height }}>
      <canvas
        ref={canvasRef}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onWheel={handleWheel}
        onClick={handleClick}
        className="w-full h-full block"
      />

      {/* Floating Canvas Controls Overlay */}
      <div className="absolute top-4 right-4 flex flex-col gap-2 z-10 bg-slate-900/80 backdrop-blur-md p-1.5 rounded-lg border border-slate-700/60 shadow-lg">
        <button
          onClick={() =>
            setViewport((v) => ({
              ...v,
              scale: Math.min(20, v.scale * 1.25),
            }))
          }
          title="Zoom In"
          className="w-8 h-8 flex items-center justify-center rounded-md text-slate-300 hover:text-white hover:bg-slate-800 transition"
        >
          <span className="material-symbols-outlined text-[18px]">add</span>
        </button>
        <button
          onClick={() =>
            setViewport((v) => ({
              ...v,
              scale: Math.max(0.01, v.scale * 0.8),
            }))
          }
          title="Zoom Out"
          className="w-8 h-8 flex items-center justify-center rounded-md text-slate-300 hover:text-white hover:bg-slate-800 transition"
        >
          <span className="material-symbols-outlined text-[18px]">remove</span>
        </button>
        <button
          onClick={fitSelectedArea}
          title="Fit Selected Study Area (Polygon)"
          className="w-8 h-8 flex items-center justify-center rounded-md text-cyan-400 hover:text-cyan-200 hover:bg-slate-800 transition"
        >
          <span className="material-symbols-outlined text-[18px]">crop</span>
        </button>
        <button
          onClick={fitNetwork}
          title="Fit Entire Network (with 500m Buffer)"
          className="w-8 h-8 flex items-center justify-center rounded-md text-slate-300 hover:text-white hover:bg-slate-800 transition"
        >
          <span className="material-symbols-outlined text-[18px]">crop_free</span>
        </button>
        <button
          onClick={fitSelectedArea}
          title="Reset View to Study Area"
          className="w-8 h-8 flex items-center justify-center rounded-md text-slate-300 hover:text-white hover:bg-slate-800 transition"
        >
          <span className="material-symbols-outlined text-[18px]">restart_alt</span>
        </button>
      </div>

      {/* Top Left Geographic Validation Badge */}
      <div className="absolute top-4 left-4 z-10 flex items-center gap-2">
        <div className="bg-slate-900/85 backdrop-blur-md px-3 py-1.5 rounded-lg border border-slate-700/60 shadow-lg text-xs text-slate-300 flex items-center gap-2">
          <span className="material-symbols-outlined text-[16px] text-cyan-400">verified</span>
          <span className="font-semibold text-white">Geographic UTM Network</span>
          <span className="text-slate-400">·</span>
          <span>{networkGeometry?.summary?.selected_area_km2 ? `${networkGeometry.summary.selected_area_km2} km²` : 'Selected Study Area'}</span>
          <span className="text-slate-400">·</span>
          <span className="text-cyan-300">{networkGeometry?.summary?.buffer_distance_m || 500}m Buffer Ext</span>
        </div>
      </div>

      {/* Network Legend / Mini-HUD Overlay */}
      <div className="absolute bottom-4 left-4 z-10 bg-slate-900/85 backdrop-blur-md px-3.5 py-2.5 rounded-lg border border-slate-700/60 shadow-lg text-xs text-slate-300 flex items-center gap-4 flex-wrap">
        <div className="flex items-center gap-1.5">
          <span className="w-4 h-0 border-t-2 border-dashed border-cyan-400 inline-block" />
          <span className="text-cyan-300 font-medium">Study Area</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-3 h-2 rounded-sm bg-slate-700 inline-block" />
          <span className="text-slate-400">External Buffer</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-sm bg-blue-500 inline-block" />
          <span>Passenger</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-3 h-2 rounded-sm bg-amber-500 inline-block" />
          <span>Bus</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-sm bg-slate-400 inline-block" />
          <span>Delivery</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-emerald-500 inline-block animate-pulse" />
          <span>Signal</span>
        </div>
        <div className="border-l border-slate-700 pl-3 flex items-center gap-1 text-slate-400 font-mono">
          <span>Active:</span>
          <strong className="text-white">{vehicles.length}</strong>
        </div>
      </div>

      {/* Hover Info Tooltip */}
      {hoveredInfo && (
        <div
          className="absolute z-20 pointer-events-none bg-slate-950/95 backdrop-blur-md border border-slate-700/80 rounded-lg p-3 shadow-xl text-xs text-slate-200 max-w-[260px]"
          style={{
            left: `${hoveredInfo.x + 14}px`,
            top: `${hoveredInfo.y + 14}px`,
          }}
        >
          <div className="font-semibold text-white text-[13px] border-b border-slate-800 pb-1 mb-1.5 flex items-center justify-between gap-3">
            <span>{hoveredInfo.title}</span>
            <span className="text-[10px] uppercase tracking-wider text-sky-400 font-mono">{hoveredInfo.subtitle}</span>
          </div>
          <div className="space-y-0.5 text-slate-300">
            {hoveredInfo.details.map((d, idx) => (
              <div key={idx}>{d}</div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Helper: Distance from point to line segment in 2D ────────────────────────
function distToSegment(px: number, py: number, x1: number, y1: number, x2: number, y2: number): number {
  const dx = x2 - x1
  const dy = y2 - y1
  const lenSq = dx * dx + dy * dy
  if (lenSq === 0) return Math.hypot(px - x1, py - y1)

  let t = ((px - x1) * dx + (py - y1) * dy) / lenSq
  t = Math.max(0, Math.min(1, t))
  const projX = x1 + t * dx
  const projY = y1 + t * dy
  return Math.hypot(px - projX, py - projY)
}
