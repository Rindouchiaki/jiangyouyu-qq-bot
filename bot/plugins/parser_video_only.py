"""解析插件调优：视频类结果只发视频，不发送渲染卡片和封面图。

上游默认行为是「渲染卡片（含封面）+ 封面图 + 视频」一起发，
这里在渲染入口做一层裁剪：只要结果里含视频，就跳过卡片、剔除图片内容。
纯 monkeypatch，不改 site-packages，升级插件不会被覆盖。
"""

from nonebot.log import logger

try:
    from nonebot_plugin_parser.parsers.data import ImageContent, VideoContent
    from nonebot_plugin_parser.renders.base import BaseRenderer, ImageRenderer
except Exception as exc:  # noqa: BLE001
    logger.warning(f"parser_video_only: 解析插件未就绪，跳过调优（{type(exc).__name__}: {exc}）")
else:
    _orig_messages = ImageRenderer.render_messages
    _orig_contents = BaseRenderer.render_contents

    def _collect_contents(result) -> list:
        items = list(getattr(result, "contents", []) or [])
        repost = getattr(result, "repost", None)
        if repost is not None:
            items += list(getattr(repost, "contents", []) or [])
        return items

    def _has_video(result) -> bool:
        return any(isinstance(c, VideoContent) for c in _collect_contents(result))

    def _strip_images(result) -> None:
        for holder in (result, getattr(result, "repost", None)):
            if holder is None:
                continue
            contents = getattr(holder, "contents", None)
            if not contents:
                continue
            try:
                holder.contents = [c for c in contents if not isinstance(c, ImageContent)]
            except Exception:  # noqa: BLE001 - 对象不可变就算了
                pass

    async def _render_messages(self):
        if not _has_video(self.result):
            async for message in _orig_messages(self):
                yield message
            return

        # 只发视频：跳过渲染卡片，并去掉封面图
        _strip_images(self.result)
        async for message in _orig_contents(self):
            yield message

    ImageRenderer.render_messages = _render_messages
    logger.info("parser_video_only: 已启用（视频类只发视频，不发封面/卡片）")
