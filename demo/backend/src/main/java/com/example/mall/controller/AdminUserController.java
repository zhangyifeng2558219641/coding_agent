package com.example.mall.controller;

import com.example.mall.dto.AdjustPointsRequest;
import com.example.mall.entity.PointRecord;
import com.example.mall.entity.User;
import com.example.mall.repository.UserRepository;
import com.example.mall.service.PointService;
import jakarta.validation.Valid;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * 管理端用户控制器(需 ADMIN):
 * GET  /api/admin/users                 用户列表
 * GET  /api/admin/users/{id}/points     任意用户积分明细流水
 * PUT  /api/admin/users/{id}/points     调整用户积分(正加负减)
 */
@RestController
@RequestMapping("/api/admin/users")
public class AdminUserController {

    private final UserRepository userRepository;
    private final PointService pointService;

    @Autowired
    public AdminUserController(UserRepository userRepository, PointService pointService) {
        this.userRepository = userRepository;
        this.pointService = pointService;
    }

    @GetMapping
    public List<User> list() {
        return userRepository.listAll();
    }

    @GetMapping("/{id}/points")
    public List<PointRecord> pointRecords(@PathVariable Long id) {
        return pointService.listByUser(id);
    }

    @PutMapping("/{id}/points")
    public User adjustPoints(@PathVariable Long id, @Valid @RequestBody AdjustPointsRequest req) {
        return pointService.adminAdjust(id, req.getPoints(), req.getRemark());
    }
}
