package com.example.mall.controller;

import com.example.mall.dto.AuthResponse;
import com.example.mall.dto.LoginRequest;
import com.example.mall.dto.RegisterRequest;
import com.example.mall.entity.User;
import com.example.mall.security.JwtUtil;
import com.example.mall.service.UserService;
import jakarta.validation.Valid;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

/**
 * 认证控制器(公开路径):
 * POST /api/auth/register 注册
 * POST /api/auth/login    登录
 * GET  /api/auth/me       获取当前登录用户(需 token)
 */
@RestController
@RequestMapping("/api/auth")
public class AuthController {

    private static final long EXPIRE_SECONDS = 12 * 60 * 60L;

    private final UserService userService;

    @Autowired
    public AuthController(UserService userService) {
        this.userService = userService;
    }

    /** 注册并直接返回 token */
    @PostMapping("/register")
    public AuthResponse register(@Valid @RequestBody RegisterRequest req) {
        User user = userService.register(req.getUsername(), req.getEmail(), req.getPassword());
        return buildAuthResponse(user);
    }

    /** 登录 */
    @PostMapping("/login")
    public AuthResponse login(@Valid @RequestBody LoginRequest req) {
        User user = userService.login(req.getEmail(), req.getPassword());
        return buildAuthResponse(user);
    }

    /** 获取当前登录用户(从拦截器注入的 userId 查询) */
    @GetMapping("/me")
    public User me(@RequestAttribute("userId") Long userId) {
        User user = userService.getById(userId);
        if (user == null) {
            throw new IllegalArgumentException("用户不存在");
        }
        return user;
    }

    private AuthResponse buildAuthResponse(User user) {
        String token = JwtUtil.generate(user.getId(), user.getUsername(), user.getRole());
        return new AuthResponse(token, EXPIRE_SECONDS, user);
    }
}
