from __future__ import annotations

from typing import Any


class AnnotationRules:
    HUMAN_LABELS = {
        "민간인",
        "군인",
    }

    VEHICLE_LABELS = {
        "민간차량",
        "소형전술차량",
        "전차",
        "자주포",
        "장갑차",
    }

    UI_ATTRIBUTE_KEYS = (
        "시선방향",
        "무기타입",
        "무기방향",
    )

    WEAPON_TYPE_OPTIONS = {
        "민간인": [],
        "군인": [
            "소총",
            "대전차화기",
            "None",
        ],
        "민간차량": [],
        "소형전술차량": [
            "원격무장",
            "None",
        ],
        "전차": [
            "원격무장",
            "포/포탑",
            "None",
        ],
        "자주포": [
            "포/포탑",
        ],
        "장갑차": [
            "포/포탑",
        ],
    }

    MULTI_WEAPON_LABELS = {
        "소형전술차량",
        "전차",
    }

    def __init__(self, config: dict[str, Any]) -> None:
        self._attribute_defs = {
            item["key"]: dict(item) for item in config.get("shape_attributes", [])
        }

    def empty_attributes(self) -> dict[str, object]:
        return {key: None for key in self._attribute_defs}

    def ui_attribute_specs(
        self,
    ) -> list[dict[str, object]]:
        specs: list[dict[str, object]] = []

        for key in self.UI_ATTRIBUTE_KEYS:
            spec = self._attribute_defs.get(key)

            if spec is not None:
                specs.append(dict(spec))

        return specs

    def layout_attribute_keys(
        self,
        label: str,
    ) -> list[str]:
        if label in self.HUMAN_LABELS:
            return [
                "시선방향",
                "무기타입",
            ]

        if label in self.VEHICLE_LABELS:
            return [
                "시선방향",
                "무기타입",
                "무기방향",
            ]

        return []

    def allows_multiple_weapon_types(
        self,
        label: str,
    ) -> bool:
        return label in self.MULTI_WEAPON_LABELS

    def weapon_type_options(
        self,
        label: str,
    ) -> list[object]:
        return list(
            self.WEAPON_TYPE_OPTIONS.get(
                label,
                [],
            )
        )

    def weapon_direction_options(
        self,
        label: str,
        weapon_type: object,
    ) -> list[object]:
        if label not in self.VEHICLE_LABELS:
            return []

        if label == "민간차량":
            return []

        if weapon_type == "None":
            return []

        attribute = self._attribute_defs.get("무기방향")

        if attribute is None:
            return []

        return list(attribute.get("options", []))

    def options_for(
        self,
        label: str,
        attribute_key: str,
        attributes: dict[str, object] | None = None,
    ) -> list[object]:
        attribute = self._attribute_defs.get(attribute_key)

        if attribute is None:
            return []

        base_options = list(attribute.get("options", []))

        if attribute_key == "시선방향":
            if label in (self.HUMAN_LABELS | self.VEHICLE_LABELS):
                return base_options

            return []

        if attribute_key == "무기타입":
            return self.weapon_type_options(label)

        if attribute_key == "무기방향":
            if label not in self.VEHICLE_LABELS:
                return []

            if label == "민간차량":
                return []

            return base_options

        return []

    def normalize_for_label(
        self,
        label: str,
        attributes: dict[str, object] | None,
    ) -> dict[str, object]:
        result = self.empty_attributes()

        if attributes:
            result.update(attributes)

        # --------------------------------------------------
        # 시선방향
        # --------------------------------------------------
        direction_options = self.options_for(
            label,
            "시선방향",
            result,
        )

        direction = result.get("시선방향")

        if direction is not None and direction not in direction_options:
            result["시선방향"] = None

        # --------------------------------------------------
        # 사람
        # --------------------------------------------------
        if label in self.HUMAN_LABELS:
            result["무기방향"] = None

            weapon_options = self.weapon_type_options(label)

            weapon_type = result.get("무기타입")

            # 민간인처럼 무기타입 자체가 없는 경우
            if not weapon_options:
                result["무기타입"] = None
                result["무장여부"] = None

            else:
                # 혹시 이전 데이터가 배열이라면
                # 사람은 첫 번째 값만 사용
                if isinstance(
                    weapon_type,
                    list,
                ):
                    weapon_type = weapon_type[0] if weapon_type else None

                if weapon_type not in weapon_options:
                    weapon_type = None

                result["무기타입"] = weapon_type

                if weapon_type is None:
                    result["무장여부"] = None

                elif weapon_type == "None":
                    result["무장여부"] = False

                else:
                    result["무장여부"] = True

            # 사람은 행동유형 필드 유지
            result["행동유형"] = []

            return result

        # --------------------------------------------------
        # 차량
        # --------------------------------------------------
        if label in self.VEHICLE_LABELS:
            # 차량에는 행동유형 없음
            result.pop(
                "행동유형",
                None,
            )

            weapon_options = self.weapon_type_options(label)

            # 민간차량
            if not weapon_options:
                result["무기타입"] = None
                result["무기방향"] = None
                result["무장여부"] = None

                return result

            raw_weapon_types = result.get("무기타입")

            raw_weapon_directions = result.get("무기방향")

            # ------------------------------
            # 기존 단일 문자열 데이터도
            # 리스트 형태로 변환
            # ------------------------------
            if raw_weapon_types is None:
                weapon_types: list[object] = []

            elif isinstance(
                raw_weapon_types,
                list,
            ):
                weapon_types = list(raw_weapon_types)

            else:
                weapon_types = [raw_weapon_types]

            if raw_weapon_directions is None:
                weapon_directions: list[object] = []

            elif isinstance(
                raw_weapon_directions,
                list,
            ):
                weapon_directions = list(raw_weapon_directions)

            else:
                weapon_directions = [raw_weapon_directions]

            # ------------------------------
            # 유효한 무기만 남김
            # 타입과 방향의 index 관계 유지
            # ------------------------------
            normalized_types: list[object] = []
            normalized_directions: list[object] = []

            seen_weapon_types: set[object] = set()

            for index, weapon_type in enumerate(weapon_types):
                if weapon_type not in weapon_options:
                    continue

                # 동일 무기 중복 제거
                if weapon_type in seen_weapon_types:
                    continue

                seen_weapon_types.add(weapon_type)

                direction = (
                    weapon_directions[index] if index < len(weapon_directions) else None
                )

                normalized_types.append(weapon_type)

                # None은 방향 없음
                if weapon_type == "None":
                    normalized_directions.append(None)
                    continue

                valid_direction_options = self.weapon_direction_options(
                    label,
                    weapon_type,
                )

                if direction not in valid_direction_options:
                    direction = None

                normalized_directions.append(direction)

            # ------------------------------
            # None은 단독 값으로 저장
            # ------------------------------
            if "None" in normalized_types:
                result["무기타입"] = "None"
                result["무기방향"] = None
                result["무장여부"] = False

                return result

            # ------------------------------
            # 자주포/장갑차처럼
            # 무기 옵션이 하나뿐이면 자동 지정
            # ------------------------------
            if not normalized_types and len(weapon_options) == 1:
                normalized_types = [weapon_options[0]]

                normalized_directions = [None]

            # ------------------------------
            # 아직 무기 선택 전
            # ------------------------------
            if not normalized_types:
                result["무기타입"] = None
                result["무기방향"] = None
                result["무장여부"] = None

                return result

            # ------------------------------
            # 실제 복수 무기 선택
            #
            # 소형전술차량 / 전차이면서
            # 실제 선택된 무기가 2개 이상일 때만
            # list 형태로 저장
            # ------------------------------
            if self.allows_multiple_weapon_types(label) and len(normalized_types) >= 2:
                result["무기타입"] = normalized_types
                result["무기방향"] = normalized_directions
                result["무장여부"] = True

                return result

            # ------------------------------
            # 나머지는 모두 단일 값으로 저장
            # ------------------------------
            result["무기타입"] = normalized_types[0]

            result["무기방향"] = (
                normalized_directions[0] if normalized_directions else None
            )

            result["무장여부"] = True

            return result

        # --------------------------------------------------
        # 정의되지 않은 클래스
        # --------------------------------------------------
        result["시선방향"] = None
        result["무기타입"] = None
        result["무기방향"] = None
        result["무장여부"] = None
        result.pop(
            "행동유형",
            None,
        )

        return result
