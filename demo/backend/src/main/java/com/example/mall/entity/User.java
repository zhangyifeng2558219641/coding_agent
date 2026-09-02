package com.example.mall.entity;

import com.fasterxml.jackson.annotation.JsonIgnore;

/**
 * 用户实体
 */
public class User {

    private Long id;
    private String username;

    /** 密码哈希,序列化时忽略,不对外暴露 */
    @JsonIgnore
    private String passwordHash;

    private String nickname;
    private String email;
    private String phone;

    /** 角色: USER(普通用户) / ADMIN(管理员) */
    private String role;

    /** 当前可用积分 */
    private int points;

    private String createdAt;

    public User() {
    }

    public Long getId() {
        return id;
    }

    public void setId(Long id) {
        this.id = id;
    }

    public String getUsername() {
        return username;
    }

    public void setUsername(String username) {
        this.username = username;
    }

    public String getPasswordHash() {
        return passwordHash;
    }

    public void setPasswordHash(String passwordHash) {
        this.passwordHash = passwordHash;
    }

    public String getNickname() {
        return nickname;
    }

    public void setNickname(String nickname) {
        this.nickname = nickname;
    }

    public String getEmail() {
        return email;
    }

    public void setEmail(String email) {
        this.email = email;
    }

    public String getPhone() {
        return phone;
    }

    public void setPhone(String phone) {
        this.phone = phone;
    }

    public String getRole() {
        return role;
    }

    public void setRole(String role) {
        this.role = role;
    }

    public int getPoints() {
        return points;
    }

    public void setPoints(int points) {
        this.points = points;
    }

    public String getCreatedAt() {
        return createdAt;
    }

    public void setCreatedAt(String createdAt) {
        this.createdAt = createdAt;
    }
}
