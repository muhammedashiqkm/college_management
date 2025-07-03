from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView
from django.contrib.auth import views as auth_views
from core.views import college_user_panel

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', RedirectView.as_view(url='/login/')),  # ✅ Redirect / to login
    path('login/', auth_views.LoginView.as_view(template_name='login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('panel/', college_user_panel, name='college-panel'),
    path('api/', include('core.urls')),
    path('api-auth/', include('rest_framework.urls')),
]
