#!/usr/bin/env python
# coding: utf-8
"""
レポートテンプレートレンダラー

Jinja2を使用してMarkdownレポートを生成
"""

from jinja2 import Environment, FileSystemLoader, select_autoescape
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class BodyReportRenderer:
    """体組成レポートのテンプレートレンダラー"""

    def __init__(self, template_dir=None):
        """
        Parameters
        ----------
        template_dir : str or Path, optional
            テンプレートディレクトリのパス
            Noneの場合はプロジェクトルート/templatesを使用
        """
        if template_dir is None:
            # プロジェクトルート/templatesをデフォルトに
            template_dir = Path(__file__).resolve().parents[3] / 'templates'

        self.env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            autoescape=select_autoescape([]),  # Markdownなのでautoescape無効
            trim_blocks=True,          # ブロックタグの改行を削除
            lstrip_blocks=True         # ブロック前の空白を削除
        )

        # カスタムフィルタを登録
        self._register_filters()

    def _register_filters(self):
        """カスタムフィルタをJinja2環境に登録"""
        from .filters import format_change, date_format, number_format

        self.env.filters['format_change'] = format_change
        self.env.filters['date_format'] = date_format
        self.env.filters['number_format'] = number_format

    def render_daily_report(self, context):
        """
        日次レポートを生成

        Parameters
        ----------
        context : dict
            テンプレートコンテキスト
            必須キー: report_title, period, summary_metrics,
                     body_composition_section, detail_data

        Returns
        -------
        str
            レンダリングされたMarkdown

        Raises
        ------
        jinja2.TemplateNotFound
            テンプレートファイルが見つからない場合
        jinja2.TemplateSyntaxError
            テンプレート構文エラーがある場合
        """
        try:
            template = self.env.get_template('body/daily_report.md.j2')
            return template.render(**context)
        except Exception as e:
            logger.error(f"Template rendering failed: {e}")
            raise

    def render_interval_report(self, context):
        """
        週次隔レポートを生成

        Parameters
        ----------
        context : dict
            テンプレートコンテキスト
            必須キー: report_title, description, progress, weekly_data

        Returns
        -------
        str
            レンダリングされたMarkdown

        Raises
        ------
        jinja2.TemplateNotFound
            テンプレートファイルが見つからない場合
        jinja2.TemplateSyntaxError
            テンプレート構文エラーがある場合
        """
        try:
            template = self.env.get_template('body/interval_report.md.j2')
            return template.render(**context)
        except Exception as e:
            logger.error(f"Template rendering failed: {e}")
            raise


class MindReportRenderer:
    """メンタルコンディションレポートのテンプレートレンダラー"""

    def __init__(self, template_dir=None):
        """
        Parameters
        ----------
        template_dir : str or Path, optional
            テンプレートディレクトリのパス
            Noneの場合はプロジェクトルート/templatesを使用
        """
        if template_dir is None:
            template_dir = Path(__file__).resolve().parents[3] / 'templates'

        self.env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            autoescape=select_autoescape([]),
            trim_blocks=True,
            lstrip_blocks=True
        )

        self._register_filters()

    def _register_filters(self):
        """カスタムフィルタをJinja2環境に登録"""
        from .filters import format_change, date_format, number_format

        self.env.filters['format_change'] = format_change
        self.env.filters['date_format'] = date_format
        self.env.filters['number_format'] = number_format

    def render_daily_report(self, context):
        """
        日次メンタルレポートを生成

        Parameters
        ----------
        context : dict
            テンプレートコンテキスト
            必須キー: report_title, period, summary_metrics, autonomic,
                     sleep_stats, physiology, daily_data, charts

        Returns
        -------
        str
            レンダリングされたMarkdown

        Raises
        ------
        jinja2.TemplateNotFound
            テンプレートファイルが見つからない場合
        jinja2.TemplateSyntaxError
            テンプレート構文エラーがある場合
        """
        try:
            template = self.env.get_template('mind/daily_report.md.j2')
            return template.render(**context)
        except Exception as e:
            logger.error(f"Template rendering failed: {e}")
            raise

    def render_interval_report(self, context):
        """
        週次隔メンタルレポートを生成

        Parameters
        ----------
        context : dict
            テンプレートコンテキスト
            必須キー: report_title, description, generated_at, weekly_data,
                     hrv_rhr_trend_image

        Returns
        -------
        str
            レンダリングされたMarkdown

        Raises
        ------
        jinja2.TemplateNotFound
            テンプレートファイルが見つからない場合
        jinja2.TemplateSyntaxError
            テンプレート構文エラーがある場合
        """
        try:
            template = self.env.get_template('mind/interval_report.md.j2')
            return template.render(**context)
        except Exception as e:
            logger.error(f"Template rendering failed: {e}")
            raise


class SleepReportRenderer:
    """睡眠分析レポートのテンプレートレンダラー"""

    def __init__(self, template_dir=None):
        """
        Parameters
        ----------
        template_dir : str or Path, optional
            テンプレートディレクトリのパス
            Noneの場合はプロジェクトルート/templatesを使用
        """
        if template_dir is None:
            template_dir = Path(__file__).resolve().parents[3] / 'templates'

        self.env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            autoescape=select_autoescape([]),
            trim_blocks=True,
            lstrip_blocks=True
        )

        self._register_filters()

    def _register_filters(self):
        """カスタムフィルタをJinja2環境に登録"""
        from .filters import format_change, date_format, number_format

        self.env.filters['format_change'] = format_change
        self.env.filters['date_format'] = date_format
        self.env.filters['number_format'] = number_format

    def render_daily_report(self, context):
        """
        日次睡眠レポートを生成

        Parameters
        ----------
        context : dict
            テンプレートコンテキスト
            必須キー: report_title, generated_at, period, summary,
                     efficiency, stages, timing, cycles

        Returns
        -------
        str
            レンダリングされたMarkdown

        Raises
        ------
        jinja2.TemplateNotFound
            テンプレートファイルが見つからない場合
        jinja2.TemplateSyntaxError
            テンプレート構文エラーがある場合
        """
        try:
            template = self.env.get_template('sleep/daily_report.md.j2')
            return template.render(**context)
        except Exception as e:
            logger.error(f"Template rendering failed: {e}")
            raise

    def render_interval_report(self, context):
        """
        週次隔睡眠レポートを生成

        Parameters
        ----------
        context : dict
            テンプレートコンテキスト
            必須キー: report_title, description, generated_at, weekly_data,
                     trend_image, debt_trend_image

        Returns
        -------
        str
            レンダリングされたMarkdown

        Raises
        ------
        jinja2.TemplateNotFound
            テンプレートファイルが見つからない場合
        jinja2.TemplateSyntaxError
            テンプレート構文エラーがある場合
        """
        try:
            template = self.env.get_template('sleep/interval_report.md.j2')
            return template.render(**context)
        except Exception as e:
            logger.error(f"Template rendering failed: {e}")
            raise


class WorkoutReportRenderer:
    """ワークアウトレポートのテンプレートレンダラー"""

    def __init__(self, template_dir=None):
        """
        Parameters
        ----------
        template_dir : str or Path, optional
            テンプレートディレクトリのパス
            Noneの場合はプロジェクトルート/templatesを使用
        """
        if template_dir is None:
            template_dir = Path(__file__).resolve().parents[3] / 'templates'

        self.env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            autoescape=select_autoescape([]),
            trim_blocks=True,
            lstrip_blocks=True
        )

        self._register_filters()

    def _register_filters(self):
        """カスタムフィルタをJinja2環境に登録"""
        from .filters import (
            format_change, date_format, number_format,
            format_volume, format_volume_simple,
            format_volume_change, format_weights
        )

        # 既存フィルタ
        self.env.filters['format_change'] = format_change
        self.env.filters['date_format'] = date_format
        self.env.filters['number_format'] = number_format

        # ワークアウト専用フィルタ
        self.env.filters['format_volume'] = format_volume
        self.env.filters['format_volume_simple'] = format_volume_simple
        self.env.filters['format_volume_change'] = format_volume_change
        self.env.filters['format_weights'] = format_weights

    def render_interval_report(self, context):
        """
        週次隔レポートを生成

        Parameters
        ----------
        context : dict
            テンプレートコンテキスト
            必須キー: report_title, description, notes,
                     training_stats, exercises, weekly_volume,
                     exercise_details

        Returns
        -------
        str
            レンダリングされたMarkdown

        Raises
        ------
        jinja2.TemplateNotFound
            テンプレートファイルが見つからない場合
        jinja2.TemplateSyntaxError
            テンプレート構文エラーがある場合
        """
        try:
            template = self.env.get_template('workout/interval_report.md.j2')
            return template.render(**context)
        except Exception as e:
            logger.error(f"Template rendering failed: {e}")
            raise
