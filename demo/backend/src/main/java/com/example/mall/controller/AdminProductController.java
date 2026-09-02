package com.example.mall.controller;

import com.example.mall.dto.ProductRequest;
import com.example.mall.dto.StatusRequest;
import com.example.mall.entity.Product;
import com.example.mall.service.ProductService;
import jakarta.validation.Valid;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * 管理端商品控制器(需 ADMIN,拦截器已校验 /api/admin/**):
 * GET  /api/admin/products           全部商品(含下架)
 * POST /api/admin/products           新增商品
 * PUT  /api/admin/products/{id}      编辑商品
 * PUT  /api/admin/products/{id}/status 上架/下架
 */
@RestController
@RequestMapping("/api/admin/products")
public class AdminProductController {

    private final ProductService productService;

    @Autowired
    public AdminProductController(ProductService productService) {
        this.productService = productService;
    }

    @GetMapping
    public List<Product> list() {
        return productService.listForAdmin();
    }

    @PostMapping
    public Product create(@Valid @RequestBody ProductRequest req) {
        return productService.create(req.getName(), req.getCategory(), req.getDescription(),
                req.getImageUrl(), req.getPrice(), req.getStock(), req.getStatus());
    }

    @PutMapping("/{id}")
    public Product update(@PathVariable Long id, @Valid @RequestBody ProductRequest req) {
        return productService.update(id, req.getName(), req.getCategory(), req.getDescription(),
                req.getImageUrl(), req.getPrice(), req.getStock());
    }

    @PutMapping("/{id}/status")
    public Product updateStatus(@PathVariable Long id, @Valid @RequestBody StatusRequest req) {
        return productService.updateStatus(id, req.getStatus());
    }
}
