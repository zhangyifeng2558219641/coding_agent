package com.example.mall.config;

import com.example.mall.security.AuthInterceptor;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

/**
 * Web 配置:注册登录鉴权拦截器。
 * 公开路径: /api/hello, /api/auth/register, /api/auth/login, /api/products(含详情/分类)
 * 其余 /api/**(含 /api/auth/me、/api/cart、/api/admin/**)均需登录 token。
 */
@Configuration
public class WebConfig implements WebMvcConfigurer {

    @Autowired
    private AuthInterceptor authInterceptor;

    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        registry.addInterceptor(authInterceptor)
                .addPathPatterns("/api/**")
                .excludePathPatterns(
                        "/api/hello",
                        "/api/auth/register",
                        "/api/auth/login",
                        "/api/products",
                        "/api/products/**");
    }
}
