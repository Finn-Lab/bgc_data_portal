"""bgc_data_portal URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/3.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.shortcuts import redirect
from django.urls import path, include, re_path
from api.api import api
from . import views
from django.conf import settings
from django.views.static import serve
from django.conf.urls.static import static
from django.views.generic import TemplateView


handler404 = 'bgc_data_portal.views.custom_404_view'

urlpatterns = [
    path('admin/', admin.site.urls),
    path("api/v1/", api.urls,name='api'),
    path('docs/', lambda request: redirect('/docs/index.html', permanent=True)),

    re_path(r'^docs/(?P<path>.*)$', serve, {'document_root': settings.BASE_DIR / 'docs/_site'}, name='docs'),
    path('', views.landing_page, name='landing_page'),
    path('bgc/<str:mgyc>/<int:start_position>/<int:end_position>/', views.bgc_page, name='bgc_page'),  # Updated URL pattern
    path('download/<str:mgyc>/<int:start_position>/<int:end_position>/', views.download_bgc_data, name='download_bgc_data'),  # New download route
    path('explore/', views.explore_view, name='explore'),


]#+ static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)



