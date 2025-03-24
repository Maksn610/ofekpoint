from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from open_webui.ragas_evaluator import ragas_evaluator

router = APIRouter(prefix="/evaluation", tags=["evaluation"])

class EvaluationRequest(BaseModel):
    question: str
    answer: str
    context: str

class BatchEvaluationRequest(BaseModel):
    questions: List[str]
    answers: List[str]
    contexts: List[str]

@router.post("/evaluate")
async def evaluate_response(request: EvaluationRequest):
    """
    Evaluates quality of a single response
    """
    result = ragas_evaluator.evaluate_single_response(
        question=request.question,
        answer=request.answer,
        context=request.context
    )
    
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["message"])
        
    return result

@router.post("/evaluate/batch")
async def evaluate_responses(request: BatchEvaluationRequest):
    """
    Evaluates quality of multiple responses in batch
    """
    if len(request.questions) != len(request.answers) or len(request.questions) != len(request.contexts):
        raise HTTPException(
            status_code=400,
            detail="Number of questions, answers and contexts must be equal"
        )
    
    result = ragas_evaluator.evaluate_responses(
        questions=request.questions,
        answers=request.answers,
        contexts=request.contexts
    )
    
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["message"])
        
    return result 