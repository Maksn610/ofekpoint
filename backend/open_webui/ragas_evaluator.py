from typing import List, Dict, Any
from ragas import evaluate
from ragas.metrics import (
    faithfulness,
    answer_relevancy,
    context_recall,
    context_precision
)
import pandas as pd
import numpy as np
from datasets import Dataset
import math
import logging
from openai import APIConnectionError

logger = logging.getLogger(__name__)

def safe_float(value: Any) -> float:
    """
    Конвертує значення в float, обробляючи спеціальні випадки
    """
    if isinstance(value, (int, float)):
        if math.isnan(value) or math.isinf(value):
            return 0.0
        return float(value)
    elif isinstance(value, (list, np.ndarray)):
        if len(value) == 0:
            return 0.0
        mean_value = np.mean(value)
        if math.isnan(mean_value) or math.isinf(mean_value):
            return 0.0
        return float(mean_value)
    return 0.0

class RagasEvaluator:
    def __init__(self):
        self.metrics = [
            faithfulness,
            answer_relevancy,
            context_recall,
            context_precision
        ]

    def evaluate_responses(
        self,
        questions: List[str],
        answers: List[str],
        contexts: List[str]
    ) -> Dict[str, Any]:
        """
        Evaluates response quality using Ragas metrics
        
        Args:
            questions: List of questions
            answers: List of answers
            contexts: List of contexts
            
        Returns:
            Dict with evaluation results
        """
        try:
            logger.info(f"Starting evaluation for {len(questions)} responses")
            
            # Convert each context string to a list containing that string for retrieved_contexts
            retrieved_contexts = [[context] for context in contexts]
            
            # Create DataFrame for Ragas with correct column names
            df = pd.DataFrame({
                "question": questions,
                "answer": answers,
                "retrieved_contexts": retrieved_contexts,
                "reference": contexts  # Using contexts directly as strings
            })
            
            # Convert DataFrame to HuggingFace Dataset
            dataset = Dataset.from_pandas(df)

            # Evaluate responses
            logger.info("Calling Ragas evaluate function")
            result = evaluate(
                dataset=dataset,
                metrics=self.metrics
            )

            # Convert results to dictionary, handling both list and single value results
            scores = {}
            for metric_name in ["faithfulness", "answer_relevancy", "context_recall", "context_precision"]:
                value = result[metric_name]
                scores[metric_name] = safe_float(value)
                logger.info(f"Metric {metric_name}: {scores[metric_name]}")

            return {
                "success": True,
                "scores": scores,
                "message": "Evaluation completed successfully"
            }

        except APIConnectionError as e:
            logger.error(f"API Connection Error during evaluation: {str(e)}")
            return {
                "success": False,
                "scores": None,
                "message": f"API Connection Error: {str(e)}"
            }
        except Exception as e:
            logger.error(f"Unexpected error during evaluation: {str(e)}", exc_info=True)
            return {
                "success": False,
                "scores": None,
                "message": f"Error during evaluation: {str(e)}"
            }

    def evaluate_single_response(
        self,
        question: str,
        answer: str,
        context: str
    ) -> Dict[str, Any]:
        """
        Evaluates quality of a single response
        
        Args:
            question: Question text
            answer: Answer text
            context: Context text
            
        Returns:
            Dict with evaluation results
        """
        return self.evaluate_responses(
            questions=[question],
            answers=[answer],
            contexts=[context]
        )

ragas_evaluator = RagasEvaluator() 