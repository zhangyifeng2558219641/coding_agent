package com.example.mall.controller;

import com.example.mall.repository.StatsRepository;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * 管理端数据看板控制器(需 ADMIN):
 * GET /api/admin/stats 销售/订单/用户/商品等汇总统计
 */
@RestController
@RequestMapping("/api/admin/stats")
public class AdminStatsController {

    private final StatsRepository statsRepository;

    @Autowired
    public AdminStatsController(StatsRepository statsRepository) {
        this.statsRepository = statsRepository;
    }

    @GetMapping
    public Map<String, Object> dashboard() {
        return statsRepository.dashboard();
    }
}
