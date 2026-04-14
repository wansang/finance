import datetime
import json
import os
from notifier import TelegramNotifier

SUMMARY_FILE = 'algorithm_update_summary.md'
LOG_FILE = 'algorithm_update_log.json'


def format_change(old, new):
    return f"{old} -> {new}"


def compute_config_changes(old_config, new_config):
    changes = {}
    for key, old_value in old_config.items():
        new_value = new_config.get(key)
        if new_value is not None and old_value != new_value:
            changes[key] = {
                'before': old_value,
                'after': new_value
            }
    return changes


def summarize_backtest(df):
    if df is None or df.empty:
        return {
            'count': 0,
            'avg_return': None,
            'win_rate': None,
            'max_return': None,
            'min_return': None
        }
    count = len(df)
    avg_return = float(df['Return(%)'].mean())
    win_rate = float((df['Return(%)'] > 0).sum() / count * 100)
    max_return = float(df['Return(%)'].max())
    min_return = float(df['Return(%)'].min())
    return {
        'count': count,
        'avg_return': avg_return,
        'win_rate': win_rate,
        'max_return': max_return,
        'min_return': min_return
    }


def describe_issues(metrics):
    notes = []
    if not metrics or metrics.get('count', 0) == 0:
        notes.append('기존 백테스트에서 유효한 추천 종목이 없어 전략 검증이 제한되었습니다.')
        return notes

    if metrics['avg_return'] is not None and metrics['avg_return'] < 0:
        notes.append('기존 전략의 평균 수익률이 음수였습니다.')
    if metrics['win_rate'] is not None and metrics['win_rate'] < 50:
        notes.append('기존 전략의 승률이 50% 미만이었습니다.')
    if metrics['max_return'] is not None and metrics['max_return'] < 0:
        notes.append('기존 전략에서는 모든 추천 종목이 손실 구간이었습니다.')
    if metrics['count'] < 5:
        notes.append('추천 종목 수가 적어 백테스트 결과의 신뢰도가 낮았습니다.')
    return notes


def format_metrics(metrics):
    if not metrics or metrics.get('count', 0) == 0:
        return '유효한 백테스트 결과가 없습니다.'
    return (
        f"추천 종목 수: {metrics['count']}개\n"
        f"평균 수익률: {metrics['avg_return']:.2f}%\n"
        f"승률: {metrics['win_rate']:.1f}%\n"
        f"최대 수익률: {metrics['max_return']:.2f}%\n"
        f"최저 수익률: {metrics['min_return']:.2f}%"
    )


class AlgorithmUpdateReport:
    def __init__(self, title, before_metrics, after_metrics, changes, notes):
        self.title = title
        self.timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.before_metrics = before_metrics
        self.after_metrics = after_metrics
        self.changes = changes
        self.notes = notes

    def build_markdown(self):
        lines = [
            f"# {self.title}",
            f"- 날짜: {self.timestamp}",
            "",
            "## 1. 변경된 항목",
        ]
        if not self.changes:
            lines.append('- 변경된 파라미터가 없습니다.')
        else:
            for key, values in self.changes.items():
                lines.append(f"- `{key}`: {values['before']} -> {values['after']}")
        lines.extend([
            "",
            "## 2. 기존 백테스트 결과",
            format_metrics(self.before_metrics),
            "",
            "## 3. 수정 후 백테스트 결과",
            format_metrics(self.after_metrics),
            "",
            "## 4. 주요 개선 포인트 및 이슈",
        ])
        if not self.notes:
            lines.append('- 특별한 이슈는 발견되지 않았습니다.')
        else:
            for note in self.notes:
                lines.append(f"- {note}")
        return '\n'.join(lines)

    def build_message(self):
        lines = [
            f"📌 {self.title}",
            f"날짜: {self.timestamp}",
            "",
            "[변경 항목]"
        ]
        if not self.changes:
            lines.append('변경된 파라미터가 없습니다.')
        else:
            for key, values in self.changes.items():
                lines.append(f"- {key}: {values['before']} -> {values['after']}")
        lines.extend([
            "",
            "[기존 백테스트]",
            format_metrics(self.before_metrics),
            "",
            "[수정 후 백테스트]",
            format_metrics(self.after_metrics),
            "",
            "[핵심 요약]"
        ])
        if not self.notes:
            lines.append('- 특별한 이슈는 발견되지 않았습니다.')
        else:
            for note in self.notes:
                lines.append(f"- {note}")
        return '\n'.join(lines)

    def save_markdown(self):
        content = self.build_markdown()
        with open(SUMMARY_FILE, 'a', encoding='utf-8') as f:
            f.write(content)
            f.write('\n\n---\n\n')
        return SUMMARY_FILE

    def save_log(self):
        log_entry = {
            'title': self.title,
            'timestamp': self.timestamp,
            'changes': self.changes,
            'before_metrics': self.before_metrics,
            'after_metrics': self.after_metrics,
            'notes': self.notes
        }
        if os.path.exists(LOG_FILE):
            try:
                with open(LOG_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception:
                data = []
        else:
            data = []
        data.append(log_entry)
        with open(LOG_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return LOG_FILE

    def send_telegram(self):
        notifier = TelegramNotifier()
        message = self.build_message()
        notifier.send_message(message)
