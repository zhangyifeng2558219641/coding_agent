package com.example.mall.controller;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * 冒烟接口(公开路径),用于快速验证服务是否存活。
 */
@RestController
public class HelloController {

    @GetMapping("/api/hello")
    public Map<String, Object> hello() {
        return Map.of("message", "商城系统后端运行中", "status", "ok");
    }
}
