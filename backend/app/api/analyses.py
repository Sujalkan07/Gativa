"""Analysis API routes: creation, retrieval, traffic flow, recommendations, and exports."""
from __future__ import annotations

import json
from fastapi import APIRouter, HTTPException, Response
from app.models.schemas import (
    CreateAnalysisRequest,
    AnalysisResult,
    TrafficFlowResult,
    RecommendationsResult,
)
from app.services.analysis import (
    run_analysis,
    get_analysis_by_id,
    get_traffic_flow_by_id,
    get_recommendations_by_id,
)

router = APIRouter(prefix="/analyses", tags=["Analyses"])


@router.post("", response_model=AnalysisResult, status_code=200)
async def create_analysis(request: CreateAnalysisRequest):
    """
    Submit a polygon for smart traffic and infrastructure analysis.

    Validates polygon coordinates, retrieves road-network from OpenStreetMap,
    gathers TomTom traffic telemetry and OpenWeather context, identifies bottlenecks,
    and produces evidence-backed infrastructure recommendations.
    """
    try:
        result = await run_analysis(request.polygon)
        return result
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Analysis pipeline error: {exc}",
        )


@router.get("/{analysis_id}", response_model=AnalysisResult)
async def get_analysis(analysis_id: str):
    """Retrieve saved analysis overview by its unique identifier."""
    result = await get_analysis_by_id(analysis_id)
    if not result:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return result


@router.get("/{analysis_id}/traffic-flow", response_model=TrafficFlowResult)
async def get_traffic_flow(analysis_id: str):
    """Retrieve road-level traffic flow, speed metrics, and active incidents for the analysis."""
    result = await get_traffic_flow_by_id(analysis_id)
    if not result:
        raise HTTPException(status_code=404, detail="Traffic flow data not found for this analysis")
    return result


@router.get("/{analysis_id}/recommendations", response_model=RecommendationsResult)
async def get_recommendations(analysis_id: str):
    """Retrieve ranked, evidence-backed engineering recommendations for the analysis."""
    result = await get_recommendations_by_id(analysis_id)
    if not result:
        raise HTTPException(status_code=404, detail="Recommendations not found for this analysis")
    return result


@router.get("/{analysis_id}/export/geojson")
async def export_geojson(analysis_id: str):
    """Export analysis road segments, bottlenecks, and polygon as a GeoJSON FeatureCollection."""
    analysis = await get_analysis_by_id(analysis_id)
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")

    features = []

    # 1. Selected area polygon
    features.append({
        "type": "Feature",
        "geometry": analysis.polygon.model_dump(),
        "properties": {
            "feature_type": "boundary",
            "analysis_id": analysis.analysis_id,
            "area_km2": analysis.area_km2,
        },
    })

    # 2. Road segments
    for seg in analysis.segments:
        if seg.geometry:
            features.append({
                "type": "Feature",
                "geometry": seg.geometry.model_dump(),
                "properties": {
                    "feature_type": "road_segment",
                    "segment_id": seg.segment_id,
                    "name": seg.name,
                    "road_type": seg.road_type,
                    "length_m": seg.length_m,
                    "observed_speed_kmh": seg.traffic.observed_speed_kmh if seg.traffic else None,
                    "congestion_level": seg.traffic.congestion_level if seg.traffic else "unknown",
                },
            })

    # 3. Bottleneck candidates
    for b in analysis.bottlenecks:
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [b.lng, b.lat],
            },
            "properties": {
                "feature_type": "bottleneck",
                "segment_id": b.segment_id,
                "location_name": b.location_name,
                "bottleneck_type": b.bottleneck_type,
                "severity": b.severity,
                "centrality_score": b.centrality_score,
                "speed_reduction": b.speed_reduction,
            },
        })

    collection = {
        "type": "FeatureCollection",
        "features": features,
    }

    return Response(
        content=json.dumps(collection, indent=2),
        media_type="application/geo+json",
        headers={
            "Content-Disposition": f'attachment; filename="gativa_analysis_{analysis_id}.geojson"'
        },
    )
