from anon import PluginManager, Plugin, Bot, logger, Permission, Storage
from anon.common import AnonExtraConfig
from anon.message import Text, Image, At, Reply, Message, Node, Forward
from anon.event import MessageEvent, GroupMessage, PrivateMessage

PluginManager().add_requirements(["msgspec~=0.19"])

import websockets
import msgspec

from websockets import WebSocketClientProtocol
from .models import *

store = Storage('gscore')

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

    res.sender = {
        'nickname': msg.sender.nickname,
        'avatar': f'http://q.qlogo.cn/headimg_dl?dst_uin={msg.sender.user_id}&spec=640&img_type=jpg'
    }
    return res


def gscore_to_msg(content: List[GSMessage]) -> Tuple[Message, Optional[Forward]]:
    res = Message()
    fwd = None
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
            case 'node':
                if not isinstance(fwd, Forward):
                    fwd = Forward(source='群聊的聊天记录', news=[])
                nick_name = store.get_or('nickname', '小助手')
                cnt = 0
                for node in i.data:
                    cnt += 1
                    i = Text(f'<unsupp: {node['type']} in node>')
                    match node['type']:
                        case 'text':
                            i = Text(node['data'])
                            fwd.news.append({'text': f'{nick_name}: {node['data']}'})
                        case 'image':
                            if node['data'].startswith('link://'):
                                i = Image(node['data'][7:])
                            else:
                                i = Image(node['data'])
                    fwd.append(Node(Message([i]), 
                                    user_id=store.get_or('user_id', 10001000),
                                    nick_name=nick_name))
                fwd.summary = f'查看{cnt}条转发消息'
            case 'group':
                continue
            case _:
                logger.debug(f'[GSUnsup] {i}')
                res.append(Text(f'<unsup: {i.type}>'))
    return (res, fwd)


class GSCoreAdapter(Plugin):
    gscore_url: str = store.get_or('url', 'ws://localhost:8765/ws/anon')
    ws: WebSocketClientProtocol = None

    async def _looper(self):
        while True:
            try:
                data = await self.ws.recv()
                send = msgspec.json.decode(data, type=MessageSend)
                seek = send.content[0]
                if seek.type.startswith('log'):
                    logger.info(f'[GSCore] [{seek.type}] {seek.data}')
                    continue

                msg, fwd = gscore_to_msg(send.content)
                if send.target_type == 'group':
                    if fwd:
                        fwd.group_id = int(send.target_id)
                    else:
                        await Bot().send_group_message(int(send.target_id), msg)
                elif send.target_type == 'direct':
                    if fwd:
                        fwd.user_id = int(send.target_id)
                    else:
                        await Bot().send_private_message(int(send.target_id), msg)
                else:
                    logger.warning(
                        f'[GSCore] unsupported send type: {send.target_type}')
                if fwd:
                    await Bot().napcat_send_forward_msg(fwd)
            except Exception as e:
                logger.warning(f'GSCore recv error: {e}')
                await self._reconnect()

    async def _reconnect(self):
        while True:
            try:
                if self.ws is None or self.ws.closed:
                    self.ws = await websockets.connect(self.gscore_url,
                                                       max_size=2**26, open_timeout=60, ping_timeout=60)
                    logger.info('[GSCore] Reconnected!')
                break
            except Exception as e:
                logger.warning(f'GSCore reconnect error: {e}')
                await asyncio.sleep(5)

    async def on_load(self):
        await self._reconnect()
        logger.info('[GSCore] Loaded!')
        PluginManager().create_task(self._looper())

    async def on_event(self, event: MessageEvent):
        if 'ww刷新面板' in event.msg.text_only:
            await event.reply('请使用 ww刷新<角色>面板！')
        try:
            await self.ws.send(msgspec.json.encode(msg_to_gscore(event)))
        except Exception as e:
            logger.warning(f'GSCoreAdapter Send Error: {e}')
            await self._reconnect()

PluginManager().register_plugin(GSCoreAdapter([MessageEvent],
                                              white_list=True,
                                              groups=AnonExtraConfig().dev_groups))
