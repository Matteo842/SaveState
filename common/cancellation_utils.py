"""Centralized cancellation utilities for background tasks"""

class CancellationManager:
    def __init__(self):
        self.is_cancelled = False
    
    def check_cancelled(self):
        """Check if cancellation has been requested"""
        return self.is_cancelled
    
    def cancel(self):
        """Signal cancellation"""
        self.is_cancelled = True
    
    def reset(self):
        """Reset cancellation state"""
        self.is_cancelled = False
