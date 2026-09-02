package com.example.mall.controller;

import com.example.mall.entity.Order;
import com.example.mall.service.OrderService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * 管理端订单控制器(需 ADMIN):
 * GET  /api/admin/orders                全部订单(可 status 筛选、keyword 按订单号/昵称/邮箱搜索、startDate/endDate 按日期筛选)
 * GET  /api/admin/orders/{id}           任意订单详情(含明细)
 * PUT  /api/admin/orders/{id}/ship      发货
 */
@RestController
@RequestMapping("/api/admin/orders")
public class AdminOrderController {

    private final OrderService orderService;

    @Autowired
    public AdminOrderController(OrderService orderService) {
        this.orderService = orderService;
    }

    @GetMapping
    public List<Order> list(@RequestParam(required = false) String status,
                            @RequestParam(required = false) String keyword,
                            @RequestParam(required = false) String startDate,
                            @RequestParam(required = false) String endDate) {
        return orderService.listAll(status, keyword, startDate, endDate);
    }

    @GetMapping("/{id}")
    public Order detail(@PathVariable Long id) {
        return orderService.adminDetail(id);
    }

    @PutMapping("/{id}/ship")
    public Order ship(@PathVariable Long id) {
        return orderService.ship(id);
    }
}
