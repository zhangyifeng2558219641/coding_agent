package com.example.mall.dto;

import com.example.mall.entity.User;

/**
 * 认证成功响应(token + 用户信息)
 */
public class AuthResponse {

    private String token;
    private long expiresIn;
    private User user;

    public AuthResponse() {
    }

    public AuthResponse(String token, long expiresIn, User user) {
        this.token = token;
        this.expiresIn = expiresIn;
        this.user = user;
    }

    public String getToken() {
        return token;
    }

    public void setToken(String token) {
        this.token = token;
    }

    public long getExpiresIn() {
        return expiresIn;
    }

    public void setExpiresIn(long expiresIn) {
        this.expiresIn = expiresIn;
    }

    public User getUser() {
        return user;
    }

    public void setUser(User user) {
        this.user = user;
    }
}
