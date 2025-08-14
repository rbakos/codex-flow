"""
Distributed messaging infrastructure for microservices communication.
Supports both Kafka and RabbitMQ backends with abstraction layer.
"""
import json
import asyncio
import uuid
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Callable, List
from datetime import datetime
from dataclasses import dataclass, asdict
from enum import Enum
import logging

import aiokafka
import aio_pika
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    """Domain event types."""
    # Project events
    PROJECT_CREATED = "project.created"
    PROJECT_UPDATED = "project.updated"
    PROJECT_DELETED = "project.deleted"
    
    # WorkItem events
    WORK_ITEM_CREATED = "workitem.created"
    WORK_ITEM_STATE_CHANGED = "workitem.state_changed"
    WORK_ITEM_COMPLETED = "workitem.completed"
    
    # Run events
    RUN_STARTED = "run.started"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"
    RUN_CLAIMED = "run.claimed"
    
    # Scheduler events
    TASK_SCHEDULED = "task.scheduled"
    TASK_READY = "task.ready"
    TASK_EXPIRED = "task.expired"
    
    # Agent events
    AGENT_REGISTERED = "agent.registered"
    AGENT_HEARTBEAT = "agent.heartbeat"
    AGENT_OFFLINE = "agent.offline"
    
    # System events
    SERVICE_HEALTH_CHANGED = "service.health_changed"
    QUOTA_EXCEEDED = "quota.exceeded"
    ALERT_TRIGGERED = "alert.triggered"


class CommandType(str, Enum):
    """Command types for CQRS."""
    CREATE_PROJECT = "cmd.create_project"
    CREATE_WORK_ITEM = "cmd.create_work_item"
    SCHEDULE_TASK = "cmd.schedule_task"
    CLAIM_RUN = "cmd.claim_run"
    COMPLETE_RUN = "cmd.complete_run"


@dataclass
class Message:
    """Base message structure."""
    id: str
    type: str
    payload: Dict[str, Any]
    metadata: Dict[str, Any]
    timestamp: datetime
    correlation_id: Optional[str] = None
    causation_id: Optional[str] = None
    
    def to_json(self) -> str:
        """Serialize message to JSON."""
        data = asdict(self)
        data['timestamp'] = self.timestamp.isoformat()
        return json.dumps(data)
    
    @classmethod
    def from_json(cls, json_str: str) -> 'Message':
        """Deserialize message from JSON."""
        data = json.loads(json_str)
        data['timestamp'] = datetime.fromisoformat(data['timestamp'])
        return cls(**data)


class Event(Message):
    """Domain event."""
    def __init__(self, event_type: EventType, payload: Dict[str, Any], **kwargs):
        super().__init__(
            id=kwargs.get('id', str(uuid.uuid4())),
            type=event_type.value,
            payload=payload,
            metadata=kwargs.get('metadata', {}),
            timestamp=kwargs.get('timestamp', datetime.utcnow()),
            correlation_id=kwargs.get('correlation_id'),
            causation_id=kwargs.get('causation_id')
        )


class Command(Message):
    """Command for CQRS."""
    def __init__(self, command_type: CommandType, payload: Dict[str, Any], **kwargs):
        super().__init__(
            id=kwargs.get('id', str(uuid.uuid4())),
            type=command_type.value,
            payload=payload,
            metadata=kwargs.get('metadata', {}),
            timestamp=kwargs.get('timestamp', datetime.utcnow()),
            correlation_id=kwargs.get('correlation_id'),
            causation_id=kwargs.get('causation_id')
        )


class MessageBus(ABC):
    """Abstract message bus interface."""
    
    @abstractmethod
    async def connect(self):
        """Connect to message broker."""
        pass
    
    @abstractmethod
    async def disconnect(self):
        """Disconnect from message broker."""
        pass
    
    @abstractmethod
    async def publish(self, topic: str, message: Message):
        """Publish message to topic."""
        pass
    
    @abstractmethod
    async def subscribe(self, topic: str, handler: Callable[[Message], None]):
        """Subscribe to topic with handler."""
        pass
    
    @abstractmethod
    async def unsubscribe(self, topic: str):
        """Unsubscribe from topic."""
        pass


class KafkaMessageBus(MessageBus):
    """Kafka implementation of message bus."""
    
    def __init__(self, bootstrap_servers: str = "localhost:9092"):
        self.bootstrap_servers = bootstrap_servers
        self.producer: Optional[aiokafka.AIOKafkaProducer] = None
        self.consumers: Dict[str, aiokafka.AIOKafkaConsumer] = {}
        self.handlers: Dict[str, List[Callable]] = {}
        self._running = False
    
    async def connect(self):
        """Connect to Kafka."""
        self.producer = aiokafka.AIOKafkaProducer(
            bootstrap_servers=self.bootstrap_servers,
            value_serializer=lambda v: v.encode('utf-8'),
            key_serializer=lambda k: k.encode('utf-8') if k else None,
            compression_type='gzip',
            max_batch_size=16384,
            linger_ms=10
        )
        await self.producer.start()
        self._running = True
        logger.info(f"Connected to Kafka at {self.bootstrap_servers}")
    
    async def disconnect(self):
        """Disconnect from Kafka."""
        self._running = False
        
        # Stop all consumers
        for consumer in self.consumers.values():
            await consumer.stop()
        
        # Stop producer
        if self.producer:
            await self.producer.stop()
        
        logger.info("Disconnected from Kafka")
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    async def publish(self, topic: str, message: Message):
        """Publish message to Kafka topic."""
        if not self.producer:
            raise RuntimeError("Not connected to Kafka")
        
        try:
            # Use correlation_id as key for ordering
            key = message.correlation_id
            value = message.to_json()
            
            await self.producer.send_and_wait(
                topic=topic,
                value=value,
                key=key
            )
            
            logger.debug(f"Published message to {topic}: {message.id}")
            
        except Exception as e:
            logger.error(f"Failed to publish message: {e}")
            raise
    
    async def subscribe(self, topic: str, handler: Callable[[Message], None]):
        """Subscribe to Kafka topic."""
        if topic not in self.consumers:
            consumer = aiokafka.AIOKafkaConsumer(
                topic,
                bootstrap_servers=self.bootstrap_servers,
                group_id=f"codex-{topic}-group",
                value_deserializer=lambda v: v.decode('utf-8'),
                auto_offset_reset='earliest',
                enable_auto_commit=True
            )
            await consumer.start()
            self.consumers[topic] = consumer
            
            # Start consumer loop
            asyncio.create_task(self._consume_loop(topic, consumer))
        
        # Add handler
        if topic not in self.handlers:
            self.handlers[topic] = []
        self.handlers[topic].append(handler)
        
        logger.info(f"Subscribed to topic: {topic}")
    
    async def unsubscribe(self, topic: str):
        """Unsubscribe from Kafka topic."""
        if topic in self.consumers:
            await self.consumers[topic].stop()
            del self.consumers[topic]
        
        if topic in self.handlers:
            del self.handlers[topic]
        
        logger.info(f"Unsubscribed from topic: {topic}")
    
    async def _consume_loop(self, topic: str, consumer: aiokafka.AIOKafkaConsumer):
        """Consumer loop for processing messages."""
        while self._running:
            try:
                async for msg in consumer:
                    if not self._running:
                        break
                    
                    # Parse message
                    try:
                        message = Message.from_json(msg.value)
                    except Exception as e:
                        logger.error(f"Failed to parse message: {e}")
                        continue
                    
                    # Call handlers
                    handlers = self.handlers.get(topic, [])
                    for handler in handlers:
                        try:
                            if asyncio.iscoroutinefunction(handler):
                                await handler(message)
                            else:
                                handler(message)
                        except Exception as e:
                            logger.error(f"Handler error: {e}")
                    
            except Exception as e:
                logger.error(f"Consumer loop error: {e}")
                await asyncio.sleep(5)  # Backoff on error


class RabbitMQMessageBus(MessageBus):
    """RabbitMQ implementation of message bus."""
    
    def __init__(self, url: str = "amqp://guest:guest@localhost/"):
        self.url = url
        self.connection: Optional[aio_pika.Connection] = None
        self.channel: Optional[aio_pika.Channel] = None
        self.exchanges: Dict[str, aio_pika.Exchange] = {}
        self.queues: Dict[str, aio_pika.Queue] = {}
    
    async def connect(self):
        """Connect to RabbitMQ."""
        self.connection = await aio_pika.connect_robust(self.url)
        self.channel = await self.connection.channel()
        await self.channel.set_qos(prefetch_count=10)
        logger.info(f"Connected to RabbitMQ at {self.url}")
    
    async def disconnect(self):
        """Disconnect from RabbitMQ."""
        if self.channel:
            await self.channel.close()
        if self.connection:
            await self.connection.close()
        logger.info("Disconnected from RabbitMQ")
    
    async def publish(self, topic: str, message: Message):
        """Publish message to RabbitMQ exchange."""
        if not self.channel:
            raise RuntimeError("Not connected to RabbitMQ")
        
        # Get or create exchange
        if topic not in self.exchanges:
            self.exchanges[topic] = await self.channel.declare_exchange(
                topic,
                aio_pika.ExchangeType.TOPIC,
                durable=True
            )
        
        exchange = self.exchanges[topic]
        
        # Publish message
        await exchange.publish(
            aio_pika.Message(
                body=message.to_json().encode(),
                correlation_id=message.correlation_id,
                message_id=message.id,
                timestamp=message.timestamp,
                content_type='application/json'
            ),
            routing_key=message.type
        )
        
        logger.debug(f"Published message to {topic}: {message.id}")
    
    async def subscribe(self, topic: str, handler: Callable[[Message], None]):
        """Subscribe to RabbitMQ queue."""
        if not self.channel:
            raise RuntimeError("Not connected to RabbitMQ")
        
        # Create queue
        queue_name = f"codex.{topic}.queue"
        if queue_name not in self.queues:
            queue = await self.channel.declare_queue(
                queue_name,
                durable=True,
                arguments={
                    'x-message-ttl': 3600000,  # 1 hour TTL
                    'x-max-length': 10000  # Max 10k messages
                }
            )
            self.queues[queue_name] = queue
            
            # Bind to exchange
            if topic in self.exchanges:
                await queue.bind(self.exchanges[topic], routing_key='#')
        
        # Start consuming
        queue = self.queues[queue_name]
        await queue.consume(
            lambda msg: self._handle_message(msg, handler),
            no_ack=False
        )
        
        logger.info(f"Subscribed to queue: {queue_name}")
    
    async def unsubscribe(self, topic: str):
        """Unsubscribe from RabbitMQ queue."""
        queue_name = f"codex.{topic}.queue"
        if queue_name in self.queues:
            queue = self.queues[queue_name]
            await queue.cancel()
            del self.queues[queue_name]
        
        logger.info(f"Unsubscribed from queue: {queue_name}")
    
    async def _handle_message(self, 
                            msg: aio_pika.IncomingMessage,
                            handler: Callable[[Message], None]):
        """Handle incoming RabbitMQ message."""
        async with msg.process():
            try:
                # Parse message
                message = Message.from_json(msg.body.decode())
                
                # Call handler
                if asyncio.iscoroutinefunction(handler):
                    await handler(message)
                else:
                    handler(message)
                    
            except Exception as e:
                logger.error(f"Failed to handle message: {e}")
                # Message will be requeued


class EventStore:
    """Event store for event sourcing."""
    
    def __init__(self, connection_string: str):
        self.connection_string = connection_string
        self.events: List[Event] = []  # In-memory for now
    
    async def append(self, stream_id: str, event: Event):
        """Append event to stream."""
        event.metadata['stream_id'] = stream_id
        event.metadata['version'] = len(self.events) + 1
        self.events.append(event)
        logger.debug(f"Appended event to stream {stream_id}: {event.id}")
    
    async def get_events(self, 
                        stream_id: str,
                        from_version: int = 0) -> List[Event]:
        """Get events from stream."""
        return [
            e for e in self.events
            if e.metadata.get('stream_id') == stream_id
            and e.metadata.get('version', 0) > from_version
        ]
    
    async def get_all_events(self, 
                            from_timestamp: Optional[datetime] = None) -> List[Event]:
        """Get all events from store."""
        if from_timestamp:
            return [e for e in self.events if e.timestamp > from_timestamp]
        return self.events


class MessageBusFactory:
    """Factory for creating message bus instances."""
    
    @staticmethod
    def create(backend: str = "kafka", **kwargs) -> MessageBus:
        """Create message bus instance."""
        if backend == "kafka":
            return KafkaMessageBus(**kwargs)
        elif backend == "rabbitmq":
            return RabbitMQMessageBus(**kwargs)
        else:
            raise ValueError(f"Unknown backend: {backend}")


# Global message bus instance
message_bus: Optional[MessageBus] = None


async def initialize_message_bus(backend: str = "kafka", **kwargs):
    """Initialize global message bus."""
    global message_bus
    message_bus = MessageBusFactory.create(backend, **kwargs)
    await message_bus.connect()
    return message_bus


async def get_message_bus() -> MessageBus:
    """Get global message bus instance."""
    if not message_bus:
        raise RuntimeError("Message bus not initialized")
    return message_bus