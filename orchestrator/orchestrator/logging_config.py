"""
Structured logging configuration for production use.
Provides JSON logging, correlation IDs, and performance tracking.
"""
import logging
import json
import sys
import time
import traceback
from datetime import datetime
from typing import Any, Dict, Optional
from contextvars import ContextVar
from pythonjsonlogger import jsonlogger
import uuid

# Context variables for request tracking
request_id_var: ContextVar[Optional[str]] = ContextVar('request_id', default=None)
trace_id_var: ContextVar[Optional[str]] = ContextVar('trace_id', default=None)
user_id_var: ContextVar[Optional[str]] = ContextVar('user_id', default=None)


class StructuredLogger:
    """Enhanced logger with structured output and context tracking."""
    
    def __init__(self, name: str):
        self.logger = logging.getLogger(name)
        self._setup_handlers()
    
    def _setup_handlers(self):
        """Configure JSON logging handlers."""
        if not self.logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            formatter = CustomJsonFormatter()
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)
    
    def _add_context(self, extra: Dict[str, Any]) -> Dict[str, Any]:
        """Add request context to log entries."""
        extra = extra or {}
        
        # Add correlation IDs
        if request_id := request_id_var.get():
            extra['request_id'] = request_id
        if trace_id := trace_id_var.get():
            extra['trace_id'] = trace_id
        if user_id := user_id_var.get():
            extra['user_id'] = user_id
            
        return extra
    
    def debug(self, message: str, **kwargs):
        """Log debug message with context."""
        extra = self._add_context(kwargs.pop('extra', {}))
        extra.update(kwargs)
        self.logger.debug(message, extra={'custom': extra})
    
    def info(self, message: str, **kwargs):
        """Log info message with context."""
        extra = self._add_context(kwargs.pop('extra', {}))
        extra.update(kwargs)
        self.logger.info(message, extra={'custom': extra})
    
    def warning(self, message: str, **kwargs):
        """Log warning message with context."""
        extra = self._add_context(kwargs.pop('extra', {}))
        extra.update(kwargs)
        self.logger.warning(message, extra={'custom': extra})
    
    def error(self, message: str, error: Optional[Exception] = None, **kwargs):
        """Log error message with exception details."""
        extra = self._add_context(kwargs.pop('extra', {}))
        extra.update(kwargs)
        
        if error:
            extra['error_type'] = type(error).__name__
            extra['error_message'] = str(error)
            extra['error_traceback'] = traceback.format_exc()
            
        self.logger.error(message, extra={'custom': extra})
    
    def critical(self, message: str, error: Optional[Exception] = None, **kwargs):
        """Log critical message with exception details."""
        extra = self._add_context(kwargs.pop('extra', {}))
        extra.update(kwargs)
        
        if error:
            extra['error_type'] = type(error).__name__
            extra['error_message'] = str(error)
            extra['error_traceback'] = traceback.format_exc()
            
        self.logger.critical(message, extra={'custom': extra})
    
    def audit(self, action: str, resource: str, result: str, **kwargs):
        """Log audit trail entry."""
        extra = self._add_context(kwargs.pop('extra', {}))
        extra.update({
            'audit_action': action,
            'audit_resource': resource,
            'audit_result': result,
            'audit_timestamp': datetime.utcnow().isoformat(),
            **kwargs
        })
        self.logger.info(f"AUDIT: {action} on {resource}: {result}", extra={'custom': extra})
    
    def performance(self, operation: str, duration_ms: float, **kwargs):
        """Log performance metrics."""
        extra = self._add_context(kwargs.pop('extra', {}))
        extra.update({
            'operation': operation,
            'duration_ms': duration_ms,
            'performance_timestamp': datetime.utcnow().isoformat(),
            **kwargs
        })
        
        level = logging.INFO
        if duration_ms > 1000:  # Warn if operation takes more than 1 second
            level = logging.WARNING
            
        self.logger.log(level, f"PERF: {operation} took {duration_ms:.2f}ms", extra={'custom': extra})


class CustomJsonFormatter(jsonlogger.JsonFormatter):
    """Custom JSON formatter with additional fields."""
    
    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        
        # Add timestamp
        log_record['timestamp'] = datetime.utcnow().isoformat()
        
        # Add level name
        log_record['level'] = record.levelname
        
        # Add module info
        log_record['module'] = record.module
        log_record['function'] = record.funcName
        log_record['line'] = record.lineno
        
        # Add custom fields if present
        if hasattr(record, 'custom'):
            log_record.update(record.custom)
        
        # Add hostname and service info
        import socket
        log_record['hostname'] = socket.gethostname()
        log_record['service'] = 'codex-orchestrator'


class PerformanceTracker:
    """Track and log performance metrics."""
    
    def __init__(self, logger: StructuredLogger):
        self.logger = logger
        self.timers: Dict[str, float] = {}
    
    def start_timer(self, operation: str):
        """Start timing an operation."""
        self.timers[operation] = time.time()
    
    def end_timer(self, operation: str, **kwargs):
        """End timing and log the result."""
        if operation not in self.timers:
            self.logger.warning(f"Timer for {operation} was not started")
            return
        
        duration_ms = (time.time() - self.timers[operation]) * 1000
        del self.timers[operation]
        
        self.logger.performance(operation, duration_ms, **kwargs)
        return duration_ms
    
    def track(self, operation: str):
        """Context manager for tracking operation duration."""
        class Timer:
            def __init__(self, tracker, op):
                self.tracker = tracker
                self.operation = op
                
            def __enter__(self):
                self.tracker.start_timer(self.operation)
                return self
                
            def __exit__(self, exc_type, exc_val, exc_tb):
                self.tracker.end_timer(self.operation)
                
        return Timer(self, operation)


class ErrorReporter:
    """Report and track errors with context."""
    
    def __init__(self, logger: StructuredLogger):
        self.logger = logger
        self.error_counts: Dict[str, int] = {}
    
    def report_error(self, error: Exception, context: Optional[Dict[str, Any]] = None):
        """Report an error with full context."""
        error_type = type(error).__name__
        self.error_counts[error_type] = self.error_counts.get(error_type, 0) + 1
        
        self.logger.error(
            f"Error occurred: {error_type}",
            error=error,
            error_count=self.error_counts[error_type],
            **(context or {})
        )
    
    def report_critical(self, error: Exception, context: Optional[Dict[str, Any]] = None):
        """Report a critical error that requires immediate attention."""
        error_type = type(error).__name__
        
        self.logger.critical(
            f"CRITICAL ERROR: {error_type}",
            error=error,
            alert_required=True,
            **(context or {})
        )
        
        # Could trigger additional alerting here (PagerDuty, Slack, etc.)
    
    def get_error_summary(self) -> Dict[str, int]:
        """Get summary of error counts."""
        return self.error_counts.copy()


def configure_logging(log_level: str = "INFO", log_file: Optional[str] = None):
    """
    Configure logging for the entire application.
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional file path for log output
    """
    # Set up root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))
    
    # Clear existing handlers
    root_logger.handlers = []
    
    # Add JSON formatter to stdout
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(CustomJsonFormatter())
    root_logger.addHandler(stdout_handler)
    
    # Add file handler if specified
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(CustomJsonFormatter())
        root_logger.addHandler(file_handler)
    
    # Configure third-party loggers
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    
    # Log startup
    logger = StructuredLogger(__name__)
    logger.info(
        "Logging configured",
        log_level=log_level,
        log_file=log_file,
        handlers=len(root_logger.handlers)
    )


def set_request_context(request_id: Optional[str] = None, 
                        trace_id: Optional[str] = None,
                        user_id: Optional[str] = None):
    """Set context variables for request tracking."""
    if request_id:
        request_id_var.set(request_id)
    else:
        request_id_var.set(str(uuid.uuid4()))
        
    if trace_id:
        trace_id_var.set(trace_id)
    if user_id:
        user_id_var.set(user_id)


def clear_request_context():
    """Clear context variables."""
    request_id_var.set(None)
    trace_id_var.set(None)
    user_id_var.set(None)


# Create global instances
logger = StructuredLogger(__name__)
performance = PerformanceTracker(logger)
errors = ErrorReporter(logger)