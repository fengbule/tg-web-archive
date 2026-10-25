"""Conservative, non-AI restoration at the source resolution and frame rate."""
from pathlib import Path

RECIPE = 'clean-sharp-v1'
# Remove weak codec edges/noise before sharpening, without a global colour boost.
FILTERS = (
    'deblock=filter=weak:block=8:alpha=0.025:beta=0.015:gamma=0.015:delta=0.015,'
    'hqdn3d=0.6:0.5:1.0:0.8,'
    'unsharp=5:5:0.45:5:5:0,'
    'pad=ceil(iw/2)*2:ceil(ih/2)*2'
)


def video_stream(streams):
    return next((s for s in streams if s.get('codec_type') == 'video'
                 and not s.get('disposition', {}).get('attached_pic')), {})


def display_size(video):
    width, height = int(video.get('width') or 0), int(video.get('height') or 0)
    rotation = video.get('tags', {}).get('rotate', 0)
    for side in video.get('side_data_list', []):
        if 'rotation' in side:
            rotation = side['rotation']
    if abs(float(rotation)) % 180 == 90:
        width, height = height, width
    return (width + width % 2, height + height % 2)


def enhancement_command(source: Path, destination: Path, streams: list) -> list[str]:
    video = video_stream(streams)
    if not video or not video.get('width') or not video.get('height'):
        raise ValueError('源文件没有可处理的视频轨道')
    if video.get('color_transfer') in ('smpte2084', 'arib-std-b67'):
        raise ValueError('暂不支持 HDR 增强，请继续使用原画，避免颜色失真')
    audio = next((s for s in streams if s.get('codec_type') == 'audio'), None)
    command = [
        'ffmpeg', '-nostdin', '-y', '-hide_banner', '-loglevel', 'error',
        '-threads', '2', '-filter_threads', '1', '-i', str(source),
        '-map', '0:V:0', '-map', '0:a:0?', '-map_metadata', '0',
        '-vf', FILTERS, '-c:v', 'libx264', '-preset', 'fast', '-crf', '17',
        '-threads', '2', '-pix_fmt', 'yuv420p', '-fps_mode', 'passthrough',
        '-force_key_frames', 'expr:gte(t,n_forced*2)', '-sc_threshold', '0',
    ]
    if audio and audio.get('codec_name') not in ('aac', 'mp3', 'alac'):
        command += ['-c:a', 'aac', '-b:a', '192k']
    else:
        command += ['-c:a', 'copy']
    return command + ['-movflags', '+faststart', '-progress', 'pipe:1', '-nostats', str(destination)]


def validate_enhancement(source_streams, output_streams):
    """Reject lost audio, scaling, or changed A/V timing before publication."""
    source, output = video_stream(source_streams), video_stream(output_streams)
    if (output.get('width'), output.get('height')) != display_size(source):
        raise ValueError('增强版分辨率校验失败，已保留原画')
    if source.get('nb_frames') and output.get('nb_frames') and source['nb_frames'] != output['nb_frames']:
        raise ValueError('增强版帧数校验失败，已保留原画')
    src_audio = next((s for s in source_streams if s.get('codec_type') == 'audio'), None)
    dst_audio = next((s for s in output_streams if s.get('codec_type') == 'audio'), None)
    if bool(src_audio) != bool(dst_audio):
        raise ValueError('增强版音轨校验失败，已保留原画')
    for before, after in [(source, output)] + ([(src_audio, dst_audio)] if src_audio else []):
        duration = float(before.get('duration') or 0)
        if duration and abs(duration - float(after.get('duration') or 0)) > .25:
            raise ValueError('增强版时长校验失败，已保留原画')
    if src_audio:
        offset = lambda v, a: float(a.get('start_time') or 0) - float(v.get('start_time') or 0)
        if abs(offset(source, src_audio) - offset(output, dst_audio)) > .1:
            raise ValueError('增强版音画时间戳校验失败，已保留原画')
