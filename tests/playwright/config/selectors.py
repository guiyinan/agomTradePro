"""
Unified selector definitions for Playwright tests.
Centralizes all CSS selectors and XPath expressions.
"""
from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class CommonSelectors:
    """Common selectors used across all pages."""

    # Navigation
    nav_sidebar: str = "nav.sidebar, aside.sidebar, .sidebar"
    nav_topbar: str = "nav.topbar, header.navbar, .navbar"
    nav_breadcrumb: str = ".breadcrumb, nav.breadcrumb, ol.breadcrumb"
    nav_home_link: str = 'a[href*="/"], a:has-text("首页"), a:has-text("Home")'

    # Menu items
    menu_toggle: str = ".menu-toggle, .navbar-toggler, button[aria-expanded]"
    menu_item: str = ".nav-item, .menu-item, li"
    menu_link: str = ".nav-link, .menu-link, a"

    # Common actions
    btn_primary: str = ".btn-primary, button[type='submit'].btn, button.btn"
    btn_secondary: str = ".btn-secondary, button.btn-outline"
    btn_danger: str = ".btn-danger, button.btn-danger"
    btn_success: str = ".btn-success, button.btn-success"

    # CRUD actions
    btn_add: str = "a:has-text('新增'), button:has-text('新增'), a:has-text('添加'), button:has-text('添加'), a:has-text('Add'), button:has-text('Add')"
    btn_edit: str = "a:has-text('编辑'), button:has-text('编辑'), a:has-text('修改'), button:has-text('修改'), a:has-text('Edit'), button:has-text('Edit')"
    btn_delete: str = "a:has-text('删除'), button:has-text('删除'), a:has-text('Delete'), button:has-text('Delete')"
    btn_save: str = "button[type='submit'], button:has-text('保存'), button:has-text('Save')"

    # Tables
    table: str = "table, .table, .data-table"
    table_row: str = "tr, .table-row"
    table_cell: str = "td, .table-cell"
    table_header: str = "th, .table-header"

    # Forms
    form: str = "form, .form"
    form_group: str = ".form-group, .mb-3"
    form_label: str = "label, .form-label"
    form_input: str = "input, textarea, select"
    form_error: str = ".error, .invalid-feedback, .text-danger"

    # Modals
    modal: str = ".modal, .dialog, [role='dialog']"
    modal_header: str = ".modal-header, .dialog-header"
    modal_body: str = ".modal-body, .dialog-body"
    modal_footer: str = ".modal-footer, .dialog-footer"
    modal_close: str = ".btn-close, button[aria-label='Close'], button:has-text('取消'), button:has-text('Cancel')"
    modal_title: str = ".modal-title, .dialog-title, h5"

    # Loading
    loading_indicator: str = ".loading, .spinner, .loader, [role='status']"
    loading_spinner: str = ".spinner-border, .fa-spinner, .loading-spinner"

    # Messages
    alert_success: str = ".alert-success, .message.success, .toast.success"
    alert_error: str = ".alert-danger, .message.error, .toast.error, .error"
    alert_warning: str = ".alert-warning, .message.warning, .toast.warning"
    alert_info: str = ".alert-info, .message.info, .toast.info"

    # Pagination
    pagination: str = ".pagination, nav[aria-label='Pagination']"
    pagination_next: str = ".pagination-next, a:has-text('下一页'), a:has-text('Next')"
    pagination_prev: str = ".pagination-prev, a:has-text('上一页'), a:has-text('Previous')"

    # Cards and panels
    card: str = ".card, .panel"
    card_header: str = ".card-header, .panel-header"
    card_body: str = ".card-body, .panel-body"
    card_footer: str = ".card-footer, .panel-footer"
    card_title: str = ".card-title, .panel-title"

    # Search and filter
    search_input: str = "input[type='search'], input[placeholder*='搜索'], input[placeholder*='Search']"
    search_btn: str = "button:has-text('搜索'), button:has-text('Search')"

    # Admin specific
    admin_logo: str = "img[alt='Django'], #site-name"
    admin_branding: str = "#site-name, h1:has-text('Django administration')"
    admin_module_list: str = "#content-main .module, .app-list"

    # Page elements
    page_title: str = "h1, .page-title, .title"
    page_header: str = ".page-header, header"

    # Links
    link: str = "a"
    external_link: str = "a[target='_blank']"

    # Dropdowns
    dropdown: str = ".dropdown, .select"
    dropdown_toggle: str = ".dropdown-toggle, [data-toggle='dropdown']"
    dropdown_menu: str = ".dropdown-menu, .select-menu"


@dataclass(frozen=True)
class AuthSelectors:
    """Selectors for authentication pages."""

    # Login page
    login_form: str = "#login-form, form[action*='login']"
    username_input: str = "#id_username, input[name='username'], input[type='text']"
    password_input: str = "#id_password, input[name='password'], input[type='password']"
    login_btn: str = "button[type='submit'], .btn-login"
    remember_me: str = "input[name='remember']"

    # Register page
    register_form: str = "#register-form, form[action*='register']"
    email_input: str = "#id_email, input[name='email'], input[type='email']"
    confirm_password_input: str = "#id_confirm_password, input[name='confirm_password']"

    # Profile page
    profile_form: str = "#profile-form, form[action*='profile']"
    change_password_btn: str = "a:has-text('修改密码'), button:has-text('修改密码')"


@dataclass(frozen=True)
class DashboardSelectors:
    """Selectors for dashboard pages."""

    # Dashboard
    dashboard_grid: str = ".dashboard-grid, .stats-grid"
    stat_card: str = ".stat-card, .metric-card, .info-box"
    chart_container: str = ".chart, .graph, canvas"
    recent_activity: str = ".recent-activity, .activity-feed"

    # Macro data
    indicator_list: str = ".indicator-list, .data-list"
    indicator_chart: str = ".indicator-chart, .data-chart"
    date_range_picker: str = ".date-range, input[type='date']"

    # Regime
    regime_quadrant: str = ".regime-quadrant, .quadrant-chart"
    regime_state: str = ".regime-state, .current-state"
    regime_history: str = ".regime-history, .history-table"

    # Signal
    signal_list: str = ".signal-list, .signals-table"
    signal_card: str = ".signal-card, .investment-signal"
    signal_filter: str = ".signal-filter, .filter-form"


@dataclass(frozen=True)
class AdminSelectors:
    """Selectors for Django Admin pages."""

    # Admin index
    admin_module: str = ".app"
    admin_model: str = ".model"
    admin_module_link: str = ".app a[href*='/admin/']"

    # Change list
    changelist_table: str = "#result_list, .result-list"
    changelist_row: str = "tr"
    changelist_actions: str = "#changelist-form .actions"
    filter_selector: str = "#changelist-filter"

    # Change form
    change_form: str = ".change-form"
    submit_row: str = ".submit-row"
    save_button: str = "_save, input[name='_save']"
    delete_link: str = "a:has-text('删除'), .deletelink"

    # Admin branding
    admin_header: str = "#header"
    admin_breadcrumb: str = ".breadcrumbs"
    admin_user_tools: str = "#user-tools"

    # Login
    admin_login_form: str = "#login-form"
    admin_error: str = ".errornote"


@dataclass(frozen=True)
class ModalSelectors:
    """Selectors specifically for modal detection."""

    # Bootstrap modal
    bootstrap_modal: str = ".modal"
    bootstrap_modal_show: str = ".modal.show"

    # Custom modal
    custom_modal: str = "[role='dialog']"
    overlay: str = ".modal-backdrop, .overlay, .backdrop"

    # Animation classes
    fade_in: str = ".fade-in, .show, .visible"
    animation_active: str = "[class*='active'], [class*='show']"


# Global selector instances
common = CommonSelectors()
auth = AuthSelectors()
dashboard = DashboardSelectors()
admin = AdminSelectors()
modal = ModalSelectors()
