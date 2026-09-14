import json
from typing import Dict, Any
from repositories.annotation_repository import AnnotationRepository


async def create_chart_annotation_tool(
    symbol: str,
    annotation_type: str,
    coordinates: Dict[str, Any],
    style: Dict[str, Any],
    label: str
) -> str:
    """
    MCP Tool: Create chart annotation (rectangle, line, etc.)

    Args:
        symbol: Trading pair
        annotation_type: Type of annotation (rectangle, line, arrow, text)
        coordinates: Coordinate data for the annotation
        style: Visual style configuration
        label: Label for the annotation

    Returns:
        JSON string with annotation ID
    """
    try:
        annotation_id = await AnnotationRepository.create_annotation(
            symbol=symbol,
            annotation_type=annotation_type,
            coordinates=coordinates,
            style=style,
            label=label
        )

        result = {
            "success": True,
            "annotation_id": annotation_id,
            "symbol": symbol,
            "type": annotation_type,
            "label": label
        }

        return json.dumps(result)

    except Exception as e:
        error_result = {
            "success": False,
            "error": str(e),
            "symbol": symbol
        }
        return json.dumps(error_result)


async def create_liquidation_zone_tool(
    symbol: str,
    start_price: float,
    end_price: float,
    start_time: int,
    end_time: int,
    label: str = "Liquidation Zone",
    strength: str = "medium"
) -> str:
    """
    MCP Tool: Create liquidation zone rectangle annotation

    Args:
        symbol: Trading pair
        start_price: Top price of zone
        end_price: Bottom price of zone
        start_time: Unix timestamp start
        end_time: Unix timestamp end
        label: Zone label
        strength: Zone strength (weak, medium, strong)

    Returns:
        JSON string with annotation ID
    """
    try:
        annotation_id = await AnnotationRepository.create_liquidation_zone_annotation(
            symbol=symbol,
            start_price=start_price,
            end_price=end_price,
            start_time=start_time,
            end_time=end_time,
            label=label,
            strength=strength
        )

        result = {
            "success": True,
            "annotation_id": annotation_id,
            "symbol": symbol,
            "zone_range": f"${end_price:.2f} - ${start_price:.2f}",
            "strength": strength
        }

        return json.dumps(result)

    except Exception as e:
        error_result = {
            "success": False,
            "error": str(e),
            "symbol": symbol
        }
        return json.dumps(error_result)


# Tool metadata for MCP server registration
ANNOTATION_TOOL_METADATA = {
    "name": "create_chart_annotation",
    "description": "Create chart annotations like rectangles, lines, arrows, or text for visualizing analysis",
    "inputSchema": {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "description": "Trading pair symbol"
            },
            "annotation_type": {
                "type": "string",
                "description": "Type of annotation",
                "enum": ["rectangle", "line", "arrow", "text"]
            },
            "coordinates": {
                "type": "object",
                "description": "Coordinate data for the annotation"
            },
            "style": {
                "type": "object",
                "description": "Visual style configuration (color, opacity, etc.)"
            },
            "label": {
                "type": "string",
                "description": "Label text for the annotation"
            }
        },
        "required": ["symbol", "annotation_type", "coordinates", "style", "label"]
    }
}

LIQUIDATION_ZONE_TOOL_METADATA = {
    "name": "create_liquidation_zone",
    "description": "Create a rectangle annotation specifically for liquidation zones on the chart",
    "inputSchema": {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "description": "Trading pair symbol"
            },
            "start_price": {
                "type": "number",
                "description": "Top price of the liquidation zone"
            },
            "end_price": {
                "type": "number",
                "description": "Bottom price of the liquidation zone"
            },
            "start_time": {
                "type": "integer",
                "description": "Unix timestamp for zone start"
            },
            "end_time": {
                "type": "integer",
                "description": "Unix timestamp for zone end"
            },
            "label": {
                "type": "string",
                "description": "Label for the zone",
                "default": "Liquidation Zone"
            },
            "strength": {
                "type": "string",
                "description": "Strength of the liquidation zone",
                "enum": ["weak", "medium", "strong"],
                "default": "medium"
            }
        },
        "required": ["symbol", "start_price", "end_price", "start_time", "end_time"]
    }
}
