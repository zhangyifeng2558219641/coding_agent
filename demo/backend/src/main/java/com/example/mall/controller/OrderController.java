package com.example.mall.controller;

import com.example.mall.dto.CreateOrderRequest;
import com.example.mall.dto.ReviewRequest;
import com.example.mall.entity.Order;
import com.example.mall.entity.Review;
import com.example.mall.service.OrderService;
import jakarta.validation.Valid;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * 用户订单控制器(需登录):
 * POST   /api/orders            从购物车创建订单
 * GET    /api/orders            我的订单列表(可 status 筛选)
 * GET    /api/orders/{id}       订单详情(含明细)
 * POST   /api/orders/{id}/pay   支付
 * POST   /api/orders/{id}/cancel 取消(仅待支付)
 * POST   /api/orders/{id}/confirm 确认收货
 * POST   /api/orders/{id}/review 评价
 */
@RestController
@RequestMapping("/api/orders")
public class OrderController {

    private final OrderService orderService;

    @Autowired
    public OrderController(OrderService orderService) {
        this.orderService = orderService;
    }

    @PostMapping
    public Order create(@RequestAttribute("userId") Long userId,
                        @Valid @RequestBody CreateOrderRequest req) {
        return orderService.create(userId, req);
    }

    @GetMapping
    public List<Order> list(@RequestAttribute("userId") Long userId,
                            @RequestParam(required = false) String status) {
        return orderService.listMine(userId, status);
    }

    @GetMapping("/{id}")
    public Order detail(@RequestAttribute("userId") Long userId, @PathVariable Long id) {
        return orderService.detail(userId, id);
    }

    @PostMapping("/{id}/pay")
    public Order pay(@RequestAttribute("userId") Long userId, @PathVariable Long id) {
        return orderService.pay(userId, id);
    }

    @PostMapping("/{id}/cancel")
    public Order cancel(@RequestAttribute("userId") Long userId, @PathVariable Long id) {
        return orderService.cancel(userId, id);
    }

    @PostMapping("/{id}/confirm")
    public Order confirm(@RequestAttribute("userId") Long userId, @PathVariable Long id) {
        return orderService.confirmReceive(userId, id);
    }

    @PostMapping("/{id}/review")
    public Review review(@RequestAttribute("userId") Long userId, @PathVariable Long id,
                         @Valid @RequestBody ReviewRequest req) {
        return orderService.review(userId, id, req);
    }
}
