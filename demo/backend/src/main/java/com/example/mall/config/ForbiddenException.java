package com.example.mall.config;

/**
 * 权限不足异常 -> HTTP 403
 */
public class ForbiddenException extends RuntimeException {

    public ForbiddenException(String message) {
        super(message);
    }
}
