"""
AgomSAAF - 视图装饰器

提供权限验证、HTMX 检测等装饰器。
"""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect


def is_htmx(request: HttpRequest) -> bool:
    """
    检查请求是否来自 HTMX

    Args:
        request: HTTP 请求对象

    Returns:
        bool: 是否为 HTMX 请求
    """
    return request.headers.get('HX-Request') == 'true'


# ========================================
# 权限装饰器
# ========================================

def staff_required(view_func):
    """
    要求用户为工作人员（staff）的装饰器

    Usage:
        @staff_required
        def my_view(request):
            ...

    Args:
        view_func: 视图函数

    Returns:
        包装后的视图函数
    """
    @login_required
    @wraps(view_func)
    def wrapper(request: HttpRequest, *args, **kwargs):
        if not request.user.is_staff:
            if is_htmx(request):
                return JsonResponse({
                    'success': False,
                    'message': '需要管理员权限'
                }, status=403, headers={
                    'X-Error-Title': '权限不足',
                    'X-Error-Message': '此操作需要管理员权限'
                })
            raise PermissionDenied('需要管理员权限')
        return view_func(request, *args, **kwargs)
    return wrapper


def superuser_required(view_func):
    """
    要求用户为超级用户的装饰器

    Usage:
        @superuser_required
        def my_view(request):
            ...

    Args:
        view_func: 视图函数

    Returns:
        包装后的视图函数
    """
    @login_required
    @wraps(view_func)
    def wrapper(request: HttpRequest, *args, **kwargs):
        if not request.user.is_superuser:
            if is_htmx(request):
                return JsonResponse({
                    'success': False,
                    'message': '需要超级管理员权限'
                }, status=403, headers={
                    'X-Error-Title': '权限不足',
                    'X-Error-Message': '此操作需要超级管理员权限'
                })
            raise PermissionDenied('需要超级管理员权限')
        return view_func(request, *args, **kwargs)
    return wrapper


def ajax_required(view_func):
    """
    要求请求为 AJAX/HTMX 的装饰器

    Usage:
        @ajax_required
        def my_view(request):
            ...

    Args:
        view_func: 视图函数

    Returns:
        包装后的视图函数
    """
    @wraps(view_func)
    def wrapper(request: HttpRequest, *args, **kwargs):
        if not request.headers.get('X-Requested-With') and not is_htmx(request):
            return JsonResponse({
                'success': False,
                'message': '此接口仅支持 AJAX 请求'
            }, status=400)
        return view_func(request, *args, **kwargs)
    return wrapper


def htmx_only(view_func):
    """
    要求请求为 HTMX 的装饰器

    Usage:
        @htmx_only
        def my_view(request):
            ...

    Args:
        view_func: 视图函数

    Returns:
        包装后的视图函数
    """
    @wraps(view_func)
    def wrapper(request: HttpRequest, *args, **kwargs):
        if not is_htmx(request):
            return JsonResponse({
                'success': False,
                'message': '此接口仅支持 HTMX 请求'
            }, status=400)
        return view_func(request, *args, **kwargs)
    return wrapper


# ========================================
# 条件装饰器
# ========================================

def conditionally(condition_decorator):
    """
    条件装饰器工厂

    根据条件决定是否应用装饰器

    Usage:
        @conditionally(condition)(decorator)
        def my_view(request):
            ...

    Args:
        condition_decorator: 包含 (condition, decorator) 的元组

    Returns:
        装饰器函数
    """
    def decorator(decorator_func):
        def wrapper(view_func):
            decorated_view = decorator_func(view_func)

            @wraps(view_func)
            def conditional_wrapper(request, *args, **kwargs):
                if condition_decorator:
                    return decorated_view(request, *args, **kwargs)
                return view_func(request, *args, **kwargs)
            return conditional_wrapper
        return wrapper
    return decorator


# ========================================
# HTMX 响应装饰器
# ========================================

def htmx_view(view_func):
    """
    HTMX 视图装饰器

    为视图添加 HTMX 响应头和自定义触发事件

    Usage:
        @htmx_view
        def my_view(request):
            return render(request, 'template.html', context)

    Args:
        view_func: 视图函数

    Returns:
        包装后的视图函数
    """
    @wraps(view_func)
    def wrapper(request: HttpRequest, *args, **kwargs):
        response = view_func(request, *args, **kwargs)

        if is_htmx(request):
            # 添加默认触发事件
            if not response.get('HX-Trigger'):
                response['HX-Trigger'] = 'contentUpdated'

            # 添加 HTMX 请求标识
            response['X-HTMX-Response'] = 'true'

        return response
    return wrapper


def htmx_trigger(event_name: str):
    """
    HTMX 事件触发装饰器工厂

    在 HTMX 响应中触发客户端事件

    Usage:
        @htmx_trigger('updateList')
        def my_view(request):
            ...

    Args:
        event_name: 要触发的事件名称

    Returns:
        装饰器函数
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request: HttpRequest, *args, **kwargs):
            response = view_func(request, *args, **kwargs)

            if is_htmx(request):
                response['HX-Trigger'] = event_name

            return response
        return wrapper
    return decorator


def htmx_redirect(view_func):
    """
    HTMX 重定向装饰器

    对于 HTMX 请求使用 HX-Redirect 头部

    Usage:
        @htmx_redirect
        def my_view(request):
            return redirect('/some-url/')

    Args:
        view_func: 视图函数

    Returns:
        包装后的视图函数
    """
    @wraps(view_func)
    def wrapper(request: HttpRequest, *args, **kwargs):
        response = view_func(request, *args, **kwargs)

        # 如果是重定向响应且为 HTMX 请求
        if is_htmx(request) and hasattr(response, 'url'):
            response['HX-Redirect'] = response.url

        return response
    return wrapper


# ========================================
# 消息装饰器
# ========================================

def success_message(message: str):
    """
    成功消息装饰器工厂

    在响应中添加成功消息

    Usage:
        @success_message('操作成功')
        def my_view(request):
            ...

    Args:
        message: 成功消息

    Returns:
        装饰器函数
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request: HttpRequest, *args, **kwargs):
            response = view_func(request, *args, **kwargs)

            if is_htmx(request):
                response['X-Success-Message'] = message
            else:
                # 对于非 HTMX 请求，使用 Django messages 框架
                from django.contrib import messages
                messages.success(request, message)

            return response
        return wrapper
    return decorator


def error_message(message: str):
    """
    错误消息装饰器工厂

    在响应中添加错误消息

    Usage:
        @error_message('操作失败')
        def my_view(request):
            ...

    Args:
        message: 错误消息

    Returns:
        装饰器函数
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request: HttpRequest, *args, **kwargs):
            response = view_func(request, *args, **kwargs)

            if is_htmx(request):
                response['X-Error-Message'] = message
            else:
                from django.contrib import messages
                messages.error(request, message)

            return response
        return wrapper
    return decorator


# ========================================
# 缓存装饰器
# ========================================

def cache_per_user(timeout: int = 300):
    """
    基于用户的缓存装饰器

    Usage:
        @cache_per_user(60)
        def my_view(request):
            ...

    Args:
        timeout: 缓存超时时间（秒）

    Returns:
        装饰器函数
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request: HttpRequest, *args, **kwargs):
            # HTMX 请求不使用缓存
            if is_htmx(request):
                return view_func(request, *args, **kwargs)

            # 非HTMX 请求可以使用缓存
            from django.core.cache import cache
            cache_key = f'user_{request.user.id}_{view_func.__name__}_{request.GET.urlencode()}'

            cached_response = cache.get(cache_key)
            if cached_response is not None:
                return cached_response

            response = view_func(request, *args, **kwargs)
            cache.set(cache_key, response, timeout)
            return response
        return wrapper
    return decorator


# ========================================
# 组合装饰器
# ========================================

def admin_htmx_view(view_func):
    """
    管理员 HTMX 视图组合装饰器

    结合了 staff_required 和 htmx_view

    Usage:
        @admin_htmx_view
        def my_view(request):
            ...

    Args:
        view_func: 视图函数

    Returns:
        包装后的视图函数
    """
    return staff_required(htmx_view(view_func))


def login_htmx_view(view_func):
    """
    登录用户 HTMX 视图组合装饰器

    结合了 login_required 和 htmx_view

    Usage:
        @login_htmx_view
        def my_view(request):
            ...

    Args:
        view_func: 视图函数

    Returns:
        包装后的视图函数
    """
    @login_required
    @htmx_view
    @wraps(view_func)
    def wrapper(request: HttpRequest, *args, **kwargs):
        return view_func(request, *args, **kwargs)
    return wrapper
