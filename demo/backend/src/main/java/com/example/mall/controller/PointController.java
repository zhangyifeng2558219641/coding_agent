package com.example.mall.controller;

import com.example.mall.entity.PointRecord;
import com.example.mall.service.PointService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * 积分流水控制器(需登录):
 * GET /api/points 我的积分流水
 */
@RestController
@RequestMapping("/api/points")
public class PointController {

    private final PointService pointService;

    @Autowired
    public PointController(PointService pointService) {
        this.pointService = pointService;
    }

    @GetMapping
    public List<PointRecord> listMine(@RequestAttribute("userId") Long userId) {
        return pointService.listMine(userId);
    }
}
