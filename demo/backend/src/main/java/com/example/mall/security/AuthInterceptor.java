package com.example.mall.security;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.stereotype.Component;
import org.springframework.web.method.HandlerMethod;
import org.springframework.web.servlet.HandlerInterceptor;

import java.io.IOException;

/**
 * 登录鉴权拦截器:
 * 校验请求头 Authorization: Bearer <token>,通过后把 userId、role 放入 request 属性。
 * 未登录/令牌无效统一返回 401。
 */
@Component
public class AuthInterceptor implements HandlerInterceptor {

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler)
            throws Exception {
        // 非 Controller 方法(静态资源等)直接放行
        if (!(handler instanceof HandlerMethod)) {
            return true;
        }

        String authorization = request.getHeader("Authorization");
        if (authorization == null || !authorization.startsWith("Bearer ")) {
            writeUnauthorized(response, "未登录或缺少令牌");
            return false;
        }

        String token = authorization.substring(7).trim();
        try {
            Long userId = JwtUtil.parse(token);
            String role = JwtUtil.getRole(token);
            request.setAttribute("userId", userId);
            request.setAttribute("role", role);

            // 管理端路径(/api/admin/**)必须 ADMIN 角色,否则 403
            if (request.getRequestURI().startsWith("/api/admin/") && !"ADMIN".equals(role)) {
                writeForbidden(response, "无权限:需要管理员身份");
                return false;
            }
            return true;
        } catch (Exception e) {
            writeUnauthorized(response, "令牌无效或已过期");
            return false;
        }
    }

    private void writeForbidden(HttpServletResponse response, String message) throws IOException {
        response.setStatus(HttpServletResponse.SC_FORBIDDEN);
        response.setContentType("application/json;charset=UTF-8");
        response.getWriter().write("{\"error\":\"" + message + "\"}");
    }

    private void writeUnauthorized(HttpServletResponse response, String message) throws IOException {
        response.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
        response.setContentType("application/json;charset=UTF-8");
        response.getWriter().write("{\"error\":\"" + message + "\"}");
    }
}
