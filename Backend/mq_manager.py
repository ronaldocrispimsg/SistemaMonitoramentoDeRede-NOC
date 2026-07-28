import asyncio
import json
import logging
import os
import aio_pika
from Backend.scheduler import process_host_check

logger = logging.getLogger("netspot.mq_manager")


class QueueManager:
    def __init__(self):
        self.connection = None
        self.channel = None
        self.dlx = None
        self.dlq = None
        self.host_check_queue = None
        self.notification_queue = None
        self.consumer_tasks = []
        self._monitor_task = None

    async def connect(self, max_attempts: int = 10, delay_seconds: float = 3.0) -> bool:
        """
        Conecta ou reconecta ao RabbitMQ utilizando aio_pika.connect_robust.
        Configura Dead Letter Exchange (DLX) e Dead Letter Queue (DLQ) para mensagens mortas/com erro.
        """
        host = os.getenv("RABBITMQ_HOST", "rabbitmq")
        port = int(os.getenv("RABBITMQ_PORT", "5672"))
        user = os.getenv("RABBITMQ_USER", "guest")
        password = os.getenv("RABBITMQ_PASSWORD", "guest")

        for attempt in range(1, max_attempts + 1):
            try:
                # Conexao robusta com reconexao automatica de transporte
                self.connection = await aio_pika.connect_robust(
                    host=host,
                    port=port,
                    login=user,
                    password=password
                )
                self.channel = await self.connection.channel()

                # 3. DLQ (Dead Letter Queue): Fila secundária para tratar erros sem perdas
                self.dlx = await self.channel.declare_exchange(
                    "netspot.dlx",
                    aio_pika.ExchangeType.DIRECT,
                    durable=True
                )
                self.dlq = await self.channel.declare_queue(
                    "netspot.dlq",
                    durable=True
                )
                await self.dlq.bind(self.dlx, routing_key="dead_letter")

                queue_args = {
                    "x-dead-letter-exchange": "netspot.dlx",
                    "x-dead-letter-routing-key": "dead_letter"
                }

                # Declaracao duravel das filas principais vinculadas a DLQ
                self.host_check_queue = await self.channel.declare_queue(
                    "netspot.host_checks",
                    durable=True,
                    arguments=queue_args
                )
                self.notification_queue = await self.channel.declare_queue(
                    "netspot.notifications",
                    durable=True,
                    arguments=queue_args
                )

                # Controle de concorrência e limite de prefetch
                await self.channel.set_qos(prefetch_count=10)

                logger.info("Conectado ao RabbitMQ com sucesso (Filas principais e DLQ ativas)!")
                
                # Inicia monitor de autocura em background se ainda nao estiver rodando
                self.start_self_healing_monitor()
                return True
            except Exception as e:
                logger.warning(
                    f"Tentativa {attempt}/{max_attempts} de conexão com RabbitMQ falhou: {e}. Retentando em {delay_seconds}s..."
                )
                await asyncio.sleep(delay_seconds)

        logger.error(f"Não foi possível conectar ao RabbitMQ após {max_attempts} tentativas.")
        return False

    def start_self_healing_monitor(self):
        """Inicia a tarefa assincrona de monitoramento continuo da conexao RabbitMQ."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        if self._monitor_task is None or self._monitor_task.done():
            self._monitor_task = loop.create_task(
                self._monitor_connection_loop(),
                name="netspot-rabbitmq-self-healing"
            )
            logger.info("Monitor de autocura do RabbitMQ iniciado em segundo plano.")

    async def _monitor_connection_loop(self):
        """
        Loop continuo que checa a integridade da conexao e canal a cada 5s.
        Em caso de queda, reconecta e re-inscreve os consumidores automaticamente.
        """
        while True:
            try:
                await asyncio.sleep(5)
                is_conn_closed = self.connection is None or self.connection.is_closed
                is_chan_closed = self.channel is None or self.channel.is_closed

                if is_conn_closed or is_chan_closed:
                    logger.warning("Queda de conexão/canal com RabbitMQ detectada! Executando autocura...")
                    success = await self.connect(max_attempts=5, delay_seconds=2.0)
                    if success:
                        await self.start_consumers()
                        logger.info("Autocura do RabbitMQ concluída: consumidores reinscritos com sucesso.")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Erro no monitor de autocura do RabbitMQ: {e}")

    async def start_consumers(self):
        """Re-inscreve ou inicia a escuta das filas de mensagens."""
        # Limpa tarefas de consumidores anteriores se existirem
        for task in self.consumer_tasks:
            if not task.done():
                task.cancel()
        self.consumer_tasks.clear()

        if not self.channel or self.channel.is_closed or not self.host_check_queue:
            logger.error("Canal do RabbitMQ invalido ou fechado ao tentar iniciar consumidores.")
            return

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

    async def _ensure_connection_active(self) -> bool:
        """Garante que a conexao e canal estejam ativos antes de publicar."""
        if self.connection is None or self.connection.is_closed or self.channel is None or self.channel.is_closed:
            logger.warning("Canal/Conexão do RabbitMQ inativo no momento da publicação. Executando reconexão sob demanda...")
            success = await self.connect(max_attempts=3, delay_seconds=1.0)
            if success:
                await self.start_consumers()
                return True
            return False
        return True

    async def publish_host_check(self, host_id: int):
        if not await self._ensure_connection_active():
            logger.error("Não é possível publicar tarefa de checagem: RabbitMQ indisponível.")
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
        if not await self._ensure_connection_active():
            logger.error("Não é possível publicar notificação: RabbitMQ indisponível.")
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
                asyncio.run_coroutine_threadsafe(self.publish_notification(payload), loop)
                return
        except RuntimeError:
            pass
        asyncio.run(self.publish_notification(payload))

    async def close(self):
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
        for task in self.consumer_tasks:
            if not task.done():
                task.cancel()
        if self.connection and not self.connection.is_closed:
            await self.connection.close()
            logger.info("Conexão com RabbitMQ fechada.")


mq_manager = QueueManager()
