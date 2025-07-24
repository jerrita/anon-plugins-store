from anon import PluginManager, Plugin, Bot, logger, Permission
from anon.common import AnonExtraConfig
from anon.message import Text, Image, At, Reply, Message
from anon.event import MessageEvent, GroupMessage, PrivateMessage

PluginManager().add_requirements(["msgspec~=0.19"])

import websockets
import msgspec

from websockets import ConnectionClosedError, WebSocketClientProtocol
from .models import *


def msg_to_gscore(msg: MessageEvent) -> MessageReceive:
    res = MessageReceive(
        bot_id='Anon',
        bot_self_id=str(msg.whoami),
        msg_id=str(msg.mid)
    )
    if isinstance(msg, GroupMessage):
        res.user_type = 'group'
        res.group_id = str(msg.gid)
    elif isinstance(msg, PrivateMessage):
        res.user_type = 'direct'

    res.user_id = str(msg.sender.user_id)
    match AnonExtraConfig().get_perm(msg.sender.user_id):
        case Permission.Owner:
            res.user_pm = 1
        case Permission.Administrator:
            res.user_pm = 3
        case _:
            res.user_pm = 6

    for obj in msg.msg:
        if isinstance(obj, Text):
            res.content.append(GSMessage('text', obj.text))
        elif isinstance(obj, At):
            res.content.append(GSMessage('at', str(obj.qq)))
        elif isinstance(obj, Reply):
            res.content.append(GSMessage('reply', str(obj.id)))
        elif isinstance(obj, Image) and obj.url:
            res.content.append(GSMessage('image', obj.url))
        else:
            res.content.append(GSMessage('text', '<unsupp>'))

    res.sender = msg.sender.data()
    return res


def gscore_to_msg(content: List[GSMessage]) -> Message:
    res = Message()
    for i in content:
        match i.type:
            case 'text':
                res.append(Text(i.data))
            case 'markdown':
                res.append(Text(i.data))
            case 'image':
                if i.data.startswith('link://'):
                    res.append(Image(i.data[7:]))
                else:
                    res.append(Image(i.data))
            case 'at':
                res.append(At(int(i.data)))
            case 'reply':
                res.append(Reply(int(i.data)))
            case 'group':
                continue
            case _:
                logger.debug(f'[GSUnsup] {i}')
                res.append(Text(f'<unsup: {i.type}>'))
    return res


class GSCoreAdapter(Plugin):
    gscore_url: str = 'ws://localhost:8765/ws/anon'
    ws: WebSocketClientProtocol

    async def _looper(self):
        while True:
            try:
                data = await self.ws.recv()
                send = msgspec.json.decode(data, type=MessageSend)
                seek = send.content[0]
                if seek.type.startswith('log'):
                    logger.info(f'[GSCore] [{seek.type}] {seek.data}')
                    continue

                msg = gscore_to_msg(send.content)
                if send.target_type == 'group':
                    await Bot().send_group_message(int(send.target_id), msg)
                elif send.target_type == 'direct':
                    await Bot().send_private_message(int(send.target_id), msg)
                else:
                    logger.warning(
                        f'[GSCore] unsupported send type: {send.target_type}')
            except Exception as e:
                logger.warning(f'GSCore recv error: {e}')
                await self._reconnect()

    async def _reconnect(self):
        while True:
            try:
                if self.ws is None or self.ws.closed:
                    self.ws = await websockets.connect(self.gscore_url)
                    logger.info('[GSCore] Reconnected!')
                break
            except Exception as e:
                logger.warning(f'GSCore reconnect error: {e}')
                await asyncio.sleep(5)

    async def on_load(self):
        try:
            self.ws = await websockets.connect(self.gscore_url)
        except Exception as e:
            await self._reconnect()
        logger.info('[GSCore] Loaded!')
        PluginManager().create_task(self._looper())

    async def on_event(self, event: MessageEvent):
        try:
            await self.ws.send(msgspec.json.encode(msg_to_gscore(event)))
        except Exception as e:
            logger.warning(f'GSCoreAdapter Send Error: {e}')
            await self._reconnect()


PluginManager().register_plugin(GSCoreAdapter([MessageEvent],
                                              perm=Permission.Owner,
                                              white_list=True,
                                              groups=AnonExtraConfig().dev_groups))
