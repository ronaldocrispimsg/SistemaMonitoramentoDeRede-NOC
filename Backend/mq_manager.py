import asyncio
import json
import logging
import os
import aio_pika
import httpx
from Backend.scheduler import process_host_check

logger = logging.getLogger("netspot.mq_manager")

class QueueManager:
    def __init__(self):
        self.connection = None
        self.channel = None
        self.host_check_queue = None
        self.notification_queue = None
        self.consumer_tasks = []

    async def connect(self):
        host = os.getenv("RABBITMQ_HOST", "rabbitmq")
        port = int(os.getenv("RABBITMQ_PORT", "5672"))
        user = os.getenv("RABBITMQ_USER", "guest")
        password = os.getenv("RABBITMQ_PASSWORD", "guest")

        # Retry logic for RabbitMQ startup robustness
        for attempt in range(1, 10):
            try:
                self.connection = await aio_pika.connect_robust(
                    host=host,
                    port=port,
                    login=user,
                    password=password
                )
                self.channel = await self.connection.channel()
                logger.info("Conectado ao RabbitMQ com sucesso!")
                break
            except Exception as e:
                logger.warning(
                    "Tentativa %s/10 de conexão com RabbitMQ falhou: %s. Re-tentando em 3s...",
                    attempt,
                    e
                )
                await asyncio.sleep(3)
        else:
            raise RuntimeError("Não foi possível conectar ao RabbitMQ após 10 tentativas.")

        # Declare Queues
        self.host_check_queue = await self.channel.declare_queue(
            "netspot.host_checks",
            durable=True
        )
        self.notification_queue = await self.channel.declare_queue(
            "netspot.notifications",
            durable=True
        )

        # Set QoS prefetch to control concurrency limit
        await self.channel.set_qos(prefetch_count=10)

    async def start_consumers(self):
        if not self.channel:
            raise RuntimeError("RabbitMQ channel not connected.")

        # Start consuming from host checks queue
        task_checks = asyncio.create_task(
            self.host_check_queue.consume(self._process_host_check_message)
        )
        self.consumer_tasks.append(task_checks)
        logger.info("Consumidores do RabbitMQ iniciados com sucesso.")

    async def _process_host_check_message(self, message: aio_pika.IncomingMessage):
        async with message.process():
            try:
                data = json.loads(message.body.decode())
                host_id = data.get("host_id")
                if host_id:
                    logger.debug("Mensagem de checagem recebida para host_id=%s", host_id)
                    await process_host_check(host_id)
            except Exception:
                logger.exception("Erro ao processar mensagem de checagem do host")

    async def publish_host_check(self, host_id: int):
        if not self.channel:
            logger.error("Não é possível publicar: canal do RabbitMQ fechado.")
            return
        payload = json.dumps({"host_id": host_id})
        await self.channel.default_exchange.publish(
            aio_pika.Message(
                body=payload.encode(),
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT
            ),
            routing_key="netspot.host_checks"
        )

    async def publish_notification(self, payload: dict | str):
        if not self.channel:
            logger.error("Não é possível publicar notificação: canal do RabbitMQ fechado.")
            return
        if isinstance(payload, str):
            body_dict = {"event": "generic", "message": payload}
        else:
            body_dict = payload
        body_bytes = json.dumps(body_dict).encode()
        await self.channel.default_exchange.publish(
            aio_pika.Message(
                body=body_bytes,
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT
            ),
            routing_key="netspot.notifications"
        )

    def publish_notification_sync(self, payload: dict | str):
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Se a event loop atual estiver rodando, agenda nela
                asyncio.run_coroutine_threadsafe(self.publish_notification(payload), loop)
                return
        except RuntimeError:
            pass
        # Fallback caso contrário: executa criando uma nova loop temporária
        asyncio.run(self.publish_notification(payload))

    async def close(self):
        for task in self.consumer_tasks:
            task.cancel()
        if self.connection:
            await self.connection.close()
            logger.info("Conexão com RabbitMQ fechada.")

mq_manager = QueueManager()
