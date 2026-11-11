"""백엔드2가 import하는 계산 모듈. DB/FastAPI/AI 의존성 없음."""
from .emissions import calculate_item
from .analysis import analyze_scenario
from .comparison import calculate_recommendation_effect, compare_scenarios
from .schemas import (CalculationError, EmissionFactor, ItemCalculation, ItemDefinition,
                      ItemInput, Variant, ScenarioAnalysis, ScenarioComparison, RecommendationEffect)

__all__ = ["calculate_item", "analyze_scenario", "calculate_recommendation_effect", "compare_scenarios",
           "CalculationError", "EmissionFactor", "ItemCalculation", "ItemDefinition", "ItemInput", "Variant",
           "ScenarioAnalysis", "ScenarioComparison", "RecommendationEffect"]
