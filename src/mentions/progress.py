"""Human-readable consolidation progress, including a stage-specific ETA."""


def duration(seconds):
    seconds = max(0, round(seconds))
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f'{hours}h {minutes:02d}m' if hours else f'{minutes}m {seconds:02d}s'


def format_progress(event):
    stage = event['stage']
    elapsed = event.get('elapsed_seconds', 0)
    if stage == 'reading_and_validating_shards':
        done, total = event.get('archives_done', 0), event.get('archives_total', 0)
        fraction = min(done / total, 1) if total else 0
        filled = int(30 * fraction)
        bar = '#' * filled + '-' * (30 - filled)
        rate = done / elapsed if elapsed > 0 else 0
        eta = duration((total - done) / rate) if rate and done >= 64 else 'calculating'
        return (f'Validate shards [{bar}] {fraction:.1%} | {done:,}/{total:,} archives | '
                f'{event.get("papers_read", 0):,} papers | {rate:.1f} archives/s | '
                f'ETA {eta} for validation | elapsed {duration(elapsed)}')
    labels = {'loading_manifest': 'Loading manifest', 'building_database': 'Building and checking SQLite',
              'saving_validated_generation': 'Saving validated outputs',
              'backing_up_previous_outputs': 'Backing up previous outputs',
              'publishing_outputs': 'Publishing outputs', 'complete': 'Consolidation complete',
              'failed': 'Consolidation failed'}
    detail = event.get('error', '')
    return f'{labels.get(stage, stage)} | elapsed {duration(elapsed)}' + (f' | {detail}' if detail else '')
