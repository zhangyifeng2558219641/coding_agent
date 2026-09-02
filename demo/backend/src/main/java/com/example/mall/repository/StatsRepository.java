package com.example.mall.repository;

import com.example.mall.entity.Order;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.math.BigDecimal;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 管理端数据看板统计(H2 + JdbcTemplate)
 */
@Repository
public class StatsRepository {

    private final JdbcTemplate jdbc;

    @Autowired
    public StatsRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    private static final String PAID_STATUSES = "('PAID','SHIPPED','COMPLETED')";

    /** 汇总统计:销售额/订单/用户/商品/今日数据/热门商品/最新订单 */
    public Map<String, Object> dashboard() {
        Map<String, Object> stats = new LinkedHashMap<>();

        // 总销售额(已支付口径)与订单总数
        BigDecimal totalSales = jdbc.queryForObject(
                "SELECT COALESCE(SUM(actual_amount),0) FROM mall_order WHERE status IN " + PAID_STATUSES,
                BigDecimal.class);
        Integer totalOrders = jdbc.queryForObject("SELECT COUNT(*) FROM mall_order", Integer.class);
        Integer pendingShip = jdbc.queryForObject(
                "SELECT COUNT(*) FROM mall_order WHERE status = 'PAID'", Integer.class);
        Integer pendingPayment = jdbc.queryForObject(
                "SELECT COUNT(*) FROM mall_order WHERE status = 'PENDING_PAYMENT'", Integer.class);

        // 用户与商品
        Integer userCount = jdbc.queryForObject("SELECT COUNT(*) FROM app_user", Integer.class);
        Integer productCount = jdbc.queryForObject("SELECT COUNT(*) FROM product", Integer.class);
        Integer onSaleCount = jdbc.queryForObject(
                "SELECT COUNT(*) FROM product WHERE status = 'ON_SALE'", Integer.class);

        // 今日订单与销售额
        Integer todayOrders = jdbc.queryForObject(
                "SELECT COUNT(*) FROM mall_order WHERE created_at >= CURRENT_DATE", Integer.class);
        BigDecimal todaySales = jdbc.queryForObject(
                "SELECT COALESCE(SUM(actual_amount),0) FROM mall_order " +
                        "WHERE created_at >= CURRENT_DATE AND status IN " + PAID_STATUSES,
                BigDecimal.class);

        // 热门商品(按销量前 5)
        List<Map<String, Object>> topProducts = jdbc.queryForList(
                "SELECT name, price, sales, avg_rating FROM product ORDER BY sales DESC LIMIT 5");

        // 最近 5 笔订单(JOIN 昵称)
        List<Map<String, Object>> recentOrders = jdbc.queryForList(
                "SELECT o.id, o.order_no, u.nickname, o.actual_amount, o.status, o.created_at " +
                        "FROM mall_order o JOIN app_user u ON o.user_id = u.id ORDER BY o.id DESC LIMIT 5");

        stats.put("totalSales", totalSales);
        stats.put("totalOrders", totalOrders);
        stats.put("pendingShip", pendingShip);
        stats.put("pendingPayment", pendingPayment);
        stats.put("userCount", userCount);
        stats.put("productCount", productCount);
        stats.put("onSaleCount", onSaleCount);
        stats.put("todayOrders", todayOrders);
        stats.put("todaySales", todaySales);
        stats.put("topProducts", topProducts);
        stats.put("recentOrders", recentOrders);
        return stats;
    }
}
