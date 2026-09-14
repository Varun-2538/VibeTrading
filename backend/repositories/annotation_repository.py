from typing import List, Dict, Any, Optional
from datetime import datetime
import json
from models.database import db


class AnnotationRepository:
    """Repository for chart annotation operations"""

    @staticmethod
    async def create_annotation(
        symbol: str,
        annotation_type: str,
        coordinates: Dict[str, Any],
        style: Dict[str, Any],
        label: str
    ) -> str:
        """
        Create a new chart annotation

        Args:
            symbol: Trading pair
            annotation_type: Type of annotation (rectangle, line, arrow, text)
            coordinates: Coordinate data
            style: Visual style data
            label: Annotation label

        Returns:
            Annotation ID
        """
        annotation_data = {
            "type": annotation_type,
            "coordinates": coordinates,
            "style": style,
            "label": label
        }

        query = """
            INSERT INTO annotations (symbol, annotation_data, created_at)
            VALUES ($1, $2, $3)
            RETURNING id
        """

        result = await db.fetchrow(
            query,
            symbol,
            json.dumps(annotation_data),
            datetime.utcnow()
        )

        return str(result['id'])

    @staticmethod
    async def get_annotations(
        symbol: str,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get chart annotations for a symbol

        Args:
            symbol: Trading pair
            limit: Maximum number of annotations to retrieve

        Returns:
            List of annotations
        """
        query = """
            SELECT id, annotation_data, created_at
            FROM annotations
            WHERE symbol = $1
            ORDER BY created_at DESC
            LIMIT $2
        """

        rows = await db.fetch(query, symbol, limit)

        annotations = []
        for row in rows:
            annotation = json.loads(row['annotation_data'])
            annotation['id'] = str(row['id'])
            annotation['created_at'] = row['created_at'].isoformat()
            annotation['symbol'] = symbol
            annotations.append(annotation)

        return annotations

    @staticmethod
    async def get_annotation_by_id(annotation_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a specific annotation by ID

        Args:
            annotation_id: Annotation ID

        Returns:
            Annotation data or None
        """
        query = """
            SELECT id, symbol, annotation_data, created_at
            FROM annotations
            WHERE id = $1
        """

        row = await db.fetchrow(query, int(annotation_id))

        if not row:
            return None

        annotation = json.loads(row['annotation_data'])
        annotation['id'] = str(row['id'])
        annotation['symbol'] = row['symbol']
        annotation['created_at'] = row['created_at'].isoformat()

        return annotation

    @staticmethod
    async def delete_annotation(annotation_id: str) -> bool:
        """
        Delete an annotation

        Args:
            annotation_id: Annotation ID

        Returns:
            True if deleted, False if not found
        """
        query = """
            DELETE FROM annotations
            WHERE id = $1
        """

        result = await db.execute(query, int(annotation_id))

        # Check if any row was deleted
        return "DELETE 1" in result

    @staticmethod
    async def create_liquidation_zone_annotation(
        symbol: str,
        start_price: float,
        end_price: float,
        start_time: int,
        end_time: int,
        label: str = "Liquidation Zone",
        strength: str = "medium"
    ) -> str:
        """
        Create a rectangle annotation for liquidation zone

        Args:
            symbol: Trading pair
            start_price: Top price of zone
            end_price: Bottom price of zone
            start_time: Unix timestamp start
            end_time: Unix timestamp end
            label: Zone label
            strength: Zone strength (weak, medium, strong)

        Returns:
            Annotation ID
        """
        # Color based on strength
        color_map = {
            "weak": "#fbbf24",      # Yellow
            "medium": "#f97316",    # Orange
            "strong": "#ef4444"     # Red
        }

        coordinates = {
            "price_start": start_price,
            "price_end": end_price,
            "time_start": start_time,
            "time_end": end_time
        }

        style = {
            "color": color_map.get(strength, "#f97316"),
            "opacity": 0.2,
            "border_color": color_map.get(strength, "#f97316"),
            "border_width": 2
        }

        return await AnnotationRepository.create_annotation(
            symbol=symbol,
            annotation_type="rectangle",
            coordinates=coordinates,
            style=style,
            label=f"{label} ({strength})"
        )

    @staticmethod
    async def create_support_resistance_line(
        symbol: str,
        price: float,
        start_time: int,
        end_time: int,
        level_type: str = "support",  # support or resistance
        strength: str = "medium"
    ) -> str:
        """
        Create a horizontal line for support/resistance level

        Args:
            symbol: Trading pair
            price: Price level
            start_time: Unix timestamp start
            end_time: Unix timestamp end
            level_type: Type of level (support or resistance)
            strength: Level strength

        Returns:
            Annotation ID
        """
        color = "#10b981" if level_type == "support" else "#ef4444"  # Green/Red
        line_style = "solid" if strength == "strong" else "dashed"

        coordinates = {
            "price": price,
            "time_start": start_time,
            "time_end": end_time
        }

        style = {
            "color": color,
            "line_width": 2 if strength == "strong" else 1,
            "line_style": line_style
        }

        label = f"{level_type.capitalize()} ({strength})"

        return await AnnotationRepository.create_annotation(
            symbol=symbol,
            annotation_type="line",
            coordinates=coordinates,
            style=style,
            label=label
        )

    @staticmethod
    async def delete_annotations_by_symbol(symbol: str) -> int:
        """
        Delete all annotations for a symbol

        Args:
            symbol: Trading pair

        Returns:
            Number of annotations deleted
        """
        query = """
            DELETE FROM annotations
            WHERE symbol = $1
        """

        result = await db.execute(query, symbol)

        # Extract number of deleted rows
        if result.startswith("DELETE"):
            return int(result.split()[-1])
        return 0

    @staticmethod
    async def get_recent_annotations(
        symbol: str,
        since: datetime,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Get annotations created after a specific time

        Args:
            symbol: Trading pair
            since: Get annotations created after this datetime
            limit: Maximum annotations to retrieve

        Returns:
            List of recent annotations
        """
        query = """
            SELECT id, annotation_data, created_at
            FROM annotations
            WHERE symbol = $1 AND created_at > $2
            ORDER BY created_at DESC
            LIMIT $3
        """

        rows = await db.fetch(query, symbol, since, limit)

        annotations = []
        for row in rows:
            annotation = json.loads(row['annotation_data'])
            annotation['id'] = str(row['id'])
            annotation['created_at'] = row['created_at'].isoformat()
            annotation['symbol'] = symbol
            annotations.append(annotation)

        return annotations
