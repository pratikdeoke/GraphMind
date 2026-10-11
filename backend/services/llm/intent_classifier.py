"""
Intent Classifier - Classify user messages into MEMORY, QUESTION, or BOTH.

Uses LLM to intelligently classify user intent.
"""

import os
from typing import Literal
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()

IntentType = Literal["MEMORY", "QUESTION", "BOTH"]


class IntentClassifier:
    """
    Classifies user messages using Gemini LLM.
    """
    
    def __init__(self):
        """Initialize LLM client."""
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel('gemini-flash-lite-latest')
        else:
            self.model = None
    
    def classify(self, message: str) -> IntentType:
        """
        Classify user message intent.
        
        Args:
            message: User's message
            
        Returns:
            Intent type: MEMORY, QUESTION, or BOTH
        """
        if not self.model:
            return self._fallback_classification(message)
        
        try:
            prompt = self._build_intent_prompt(message)
            response = self.model.generate_content(prompt)
            intent_text = response.text.strip().upper()
            
            if "BOTH" in intent_text:
                return "BOTH"
            elif "MEMORY" in intent_text:
                return "MEMORY"
            elif "QUESTION" in intent_text:
                return "QUESTION"
            else:
                return "QUESTION"  # Default
                
        except Exception as e:
            print(f"Error in intent classification: {e}")
            return self._fallback_classification(message)
    
    def _build_intent_prompt(self, message: str) -> str:
        """Build the intent classification prompt."""
        return f"""You are an intent classifier for a financial assistant system.

Classify the following user message into one of these THREE categories:

1. MEMORY - User is providing information to be stored (investments, transactions, financial data, goals, etc.)
   Examples:
   - "I invested 50,000 in HDFC mutual fund"
   - "I bought 100 shares of TCS"
   - "My retirement goal is 1 crore"

2. QUESTION - User is asking a question or requesting information
   Examples:
   - "What assets do I own?"
   - "Show me my portfolio"
   - "Am I aligned with my retirement goal?"

3. BOTH - User is providing information AND asking a question in the same message
   Examples:
   - "I invested 50,000 in HDFC MF. Am I aligned with my goal?"
   - "I bought stocks worth 1 lakh. How is my portfolio performing?"

User message: "{message}"

Respond with ONLY one word: MEMORY, QUESTION, or BOTH"""
    
    def _fallback_classification(self, message: str) -> IntentType:
        """Fallback keyword-based classification."""
        message_lower = message.lower()
        
        memory_keywords = ["invested", "bought", "spent", "earned", "saved", "deposited", "purchased", "sold"]
        question_keywords = ["what", "how", "which", "am i", "do i", "show", "tell", "explain", "list"]
        
        has_memory = any(keyword in message_lower for keyword in memory_keywords)
        has_question = any(keyword in message_lower for keyword in question_keywords) or "?" in message
        
        if has_memory and has_question:
            return "BOTH"
        elif has_memory:
            return "MEMORY"
        else:
            return "QUESTION"
